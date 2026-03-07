# Real-Time Market Analytics — Kafka · Spark · Hive

> **DATA 228 · Big Data Technologies · San Jose State University**
> A complete end-to-end streaming data pipeline that ingests live stock-market bar data from the Alpaca Markets API, processes it in real time with PySpark Structured Streaming, stores enriched results in Apache Hive (Parquet), and visualises trends on an interactive Plotly-Dash dashboard — all orchestrated with Docker Compose.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Pipeline Data Flow](#3-pipeline-data-flow)
4. [Repository Structure](#4-repository-structure)
5. [Component Deep-Dive](#5-component-deep-dive)
6. [Setup & Prerequisites](#6-setup--prerequisites)
7. [Configuration](#7-configuration)
8. [Running the Pipeline](#8-running-the-pipeline)
9. [Hive Queries & Monitoring](#9-hive-queries--monitoring)
10. [Technical Difficulties & Best Practices](#10-technical-difficulties--best-practices)
11. [Learning Summary & Reflections](#11-learning-summary--reflections)
12. [Future Improvements](#12-future-improvements)

---

## 1. Project Overview

This project implements a **real-time trend analyzer** for US equity markets using the following tech stack:

| Layer | Technology |
|---|---|
| Data Source | Alpaca Markets WebSocket API (live bar data) |
| Message Broker | Apache Kafka 3.5 (via Confluent Docker image) |
| Stream Processor | Apache Spark 3.5 — PySpark Structured Streaming |
| Storage | Apache Hive 2.3 on HDFS (Parquet format) |
| Visualization | Plotly Dash (Python web dashboard) |
| Infrastructure | Docker Compose (10-container stack) |
| Mock Testing | Custom Python mock producer with trend simulation |

### Stocks Tracked
`AAPL` · `TSLA` · `GOOGL` · `MSFT` · `AMZN`

### What the Pipeline Computes (per 5-minute sliding window)
- Average, max, and min close price
- Price volatility (standard deviation of close prices)
- Average trading volume
- Average VWAP and VWAP deviation %
- Buy pressure (fraction of bars where price moved up)
- Average percentage change
- **Trend signal**: `BULLISH` / `BEARISH` / `NEUTRAL`

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                             │
│                                                                 │
│   Alpaca Markets API          Mock Producer (testing)           │
│   (WebSocket live bars)       (simulated OHLCV data)            │
└──────────────┬──────────────────────────┬───────────────────────┘
               │                          │
               ▼                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    APACHE KAFKA (port 29092)                     │
│                                                                 │
│   Topic: alpaca_trends          Topic: alpaca_trend_results     │
│   (raw preprocessed bars)       (Spark-computed aggregates)     │
└──────────────┬──────────────────────────┬───────────────────────┘
               │                          ▲
               ▼                          │
┌─────────────────────────────────────────────────────────────────┐
│              APACHE SPARK STRUCTURED STREAMING                  │
│                                                                 │
│  • Reads from alpaca_trends                                     │
│  • 5-min sliding windows (1-min slide) with 2-min watermark     │
│  • Computes: avg/max/min close, volatility, buy pressure,       │
│    VWAP deviation, trend signal                                 │
│  • Writes results → Kafka + Hive + Console                      │
└──────────────┬──────────────────────────┬───────────────────────┘
               │                          │
               ▼                          ▼
┌───────────────────────┐   ┌─────────────────────────────────────┐
│     APACHE HIVE       │   │         PLOTLY DASH DASHBOARD       │
│                       │   │                                     │
│  Table: stock_trends  │   │  • Avg close price (line chart)     │
│  Format: Parquet      │   │  • Price range OHLC (box chart)     │
│  on HDFS              │   │  • Buy pressure % (line chart)      │
│                       │   │  • Volatility (bar chart)           │
└───────────────────────┘   │  • Avg volume (line chart)          │
                            │  • Signal badges (BULLISH/BEARISH)  │
                            │  • Auto-refreshes every 5 seconds   │
                            └─────────────────────────────────────┘
```

### Docker Compose Services

```
zookeeper              ← Kafka coordination (port 2181)
kafka                  ← Message broker (ports 9092, 29092)
namenode               ← HDFS NameNode (ports 50070, 9000)
datanode               ← HDFS DataNode (port 9864)
hdfs-init              ← One-time job: creates /user/hive/warehouse
hive-metastore-postgresql ← Postgres backend for Hive metastore
hive-metastore         ← Hive Thrift Metastore (port 9083)
hive-server            ← HiveServer2 for JDBC/Beeline (port 10000)
spark-master           ← Spark Master UI (port 8080)
spark-worker           ← Spark Worker UI (port 8081)
```

---

## 3. Pipeline Data Flow

```
Step 1  Alpaca WebSocket stream → bars arrive for each subscribed symbol
Step 2  alpaca_producer.py preprocesses each bar:
           open, high, low, close, volume, vwap
           + price_change, pct_change, direction (up/down/flat)
           + ingested_at timestamp
Step 3  Preprocessed JSON record is published to Kafka topic: alpaca_trends
           (keyed by stock symbol for partition locality)
Step 4  spark_trend_analyzer.py reads from alpaca_trends via Structured Streaming
Step 5  Spark applies a 5-minute sliding window (sliding every 1 minute)
           with a 2-minute watermark for late-arrival tolerance
Step 6  Aggregated results (trend windows) are written to:
           → Kafka topic alpaca_trend_results  (for the dashboard)
           → HDFS in Parquet format            (via Hive warehouse path)
           → Console                           (for debugging)
Step 7  dashboard.py consumes alpaca_trend_results and renders 5 charts
           refreshing every 5 seconds
```

---

## 4. Repository Structure

```
realtime-market-analytics-kafka-spark-hive/
│
├── alpaca_producer.py       # Live Kafka producer using Alpaca WebSocket API
├── mock_producer.py         # Simulated producer for offline testing
├── spark_trend_analyzer.py  # PySpark Structured Streaming job
├── dashboard.py             # Plotly Dash real-time web dashboard
│
├── docker-compose.yml       # Full 10-container infrastructure stack
├── hive-site.xml            # Hive metastore configuration (Postgres backend)
│
├── .env.example             # Template for API keys and config
├── requirements.txt         # Python package dependencies
├── .gitignore               # Excludes .env, __pycache__, checkpoints, etc.
└── README.md                # This file
```

---

## 5. Component Deep-Dive

### 5.1 `alpaca_producer.py` — Live Kafka Producer

This script is the **entry point for live data**. It opens a persistent WebSocket connection to Alpaca's market data stream and subscribes to minute-bar events for all configured symbols.

**Key design decisions:**

- **Environment variables** — API keys and broker URL are loaded from `.env` via `python-dotenv`. This keeps secrets out of source control entirely.
- **Preprocessing at ingestion** — Rather than forwarding raw Alpaca objects, the producer immediately computes derived fields (`price_change`, `pct_change`, `direction`) before sending to Kafka. This reduces the complexity of downstream Spark logic and makes the Kafka messages self-contained.
- **Keyed messages** — Each Kafka message is keyed by `symbol`. This guarantees that all records for the same stock land in the same Kafka partition, enabling ordered, per-symbol consumption in Spark.
- **Retry loop** — If the WebSocket connection drops (Alpaca occasionally closes idle connections), the producer catches the exception and reconnects after a configurable delay. It gives up after `MAX_RETRIES` attempts, which prevents infinite loops in broken environments.
- **Structured logging** — All output goes through Python's `logging` module so that log levels can be controlled at runtime and logs can be redirected to files or log aggregators.

**Alpaca bar fields used:**

| Field | Description |
|---|---|
| `symbol` | Ticker symbol (e.g. AAPL) |
| `timestamp` | Bar close time (ISO 8601) |
| `open` / `close` / `high` / `low` | OHLC prices |
| `volume` | Number of shares traded in the bar |
| `vwap` | Volume-weighted average price |

---

### 5.2 `mock_producer.py` — Simulated Kafka Producer

Used when you want to test the full pipeline without a live Alpaca subscription. It generates synthetic OHLCV data for the same five symbols and publishes at a fixed interval.

**Simulation model:**

Each symbol maintains a `current_price` that random-walks each tick. A **trend bias** is layered on top: a small signed drift value added to the random walk. Every `BIAS_SHIFT_INTERVAL` rounds, the biases are randomly perturbed. If a symbol drifts more than 3% away from its base price, a **mean-reversion force** automatically flips the bias back toward center. This creates realistic bull and bear micro-cycles visible in the dashboard.

Volume is also modulated by bias magnitude — stronger trends produce higher simulated volume, matching real-market behavior where momentum attracts more participation.

---

### 5.3 `spark_trend_analyzer.py` — PySpark Structured Streaming

This is the analytical core of the pipeline.

**Session configuration:**
- `enableHiveSupport()` — allows Spark to write DDL and query Hive tables
- `hive.metastore.uris` — points to the containerised Thrift metastore
- Checkpoint directory on local `/tmp` — stores Spark streaming state across micro-batches

**Schema enforcement:**
A strict `StructType` schema is defined for the incoming JSON. This prevents schema inference overhead and catches malformed messages at parse time (they produce `null` values rather than crashing the stream).

**Windowed aggregation:**
```
5-minute windows, sliding every 1 minute
Watermark: 2 minutes (late events within 2 min are still included)
```
The sliding window means each event is included in up to five windows, giving smooth trend lines rather than choppy 5-minute bars.

**Metrics computed per symbol per window:**

| Metric | Formula |
|---|---|
| `avg_close` | Mean close price across all bars in window |
| `max_close` / `min_close` | Highest and lowest close |
| `volatility` | Standard deviation of close prices |
| `avg_volume` | Mean bar volume |
| `avg_vwap` | Mean VWAP |
| `avg_pct_change` | Mean per-bar % change |
| `buy_pressure` | `count(direction=="up") / count(*)` |
| `price_range` | `max_close - min_close` |
| `vwap_deviation_pct` | `(avg_close - avg_vwap) / avg_vwap × 100` |

**Trend signal logic:**
```
If avg_close > min_close + price_range × 0.6  →  BULLISH
If avg_close < min_close + price_range × 0.4  →  BEARISH
Otherwise                                      →  NEUTRAL
```
This positions the average close relative to the window's price range. When the average is in the upper 40% of the range, it indicates sustained buying pressure (BULLISH); lower 40% indicates sustained selling (BEARISH).

**Three output sinks:**
1. **Console** — for real-time debugging during development
2. **Kafka** (`alpaca_trend_results`) — feeds the dashboard
3. **Hive/HDFS** — persistent Parquet storage for historical queries

---

### 5.4 `dashboard.py` — Plotly Dash Web Dashboard

A Python web application that subscribes to the `alpaca_trend_results` Kafka topic in a background thread and renders five live-updating charts.

**Thread safety:** A `threading.Lock` protects `data_store` (a `defaultdict` of `deque`s). The Kafka consumer thread writes to it; the Dash callback thread reads from it via a snapshot copy.

**Charts:**

| Chart | Type | Description |
|---|---|---|
| Signal badges | HTML spans | Color-coded BULLISH/BEARISH/NEUTRAL per symbol with avg close and buy pressure |
| Avg close price | Line chart | Trend of average close per window for all symbols |
| Price range | Box chart | Min/avg/max close per symbol, showing spread |
| Buy pressure % | Line + threshold | % of up-ticks per window; 50% line marks neutral |
| Volatility | Grouped bar | Standard deviation of close per window |
| Avg volume | Dotted line | Trading activity trend over time |

Auto-refresh interval: **5 seconds** (configurable via `dcc.Interval`).

---

### 5.5 `docker-compose.yml` — Infrastructure Stack

The compose file spins up a complete, self-contained big data environment in one command.

**Networking:** All containers share the default Docker bridge network. Internal services communicate via container names (e.g., `kafka:9092`, `namenode:9000`). The host machine accesses Kafka via the mapped port `29092`.

**HDFS initialisation:** The `hdfs-init` service is a one-shot container that waits for the NameNode to become healthy, then creates the `/user/hive/warehouse` and `/tmp/hive` directories with open permissions. Without this, Hive's first write fails because the warehouse path does not exist.

**Hive metastore backend:** The default Derby embedded database is replaced with a dedicated PostgreSQL container (`hive-metastore-postgresql`). Derby is not safe for concurrent access and frequently corrupts its store when multiple processes (Hive + Spark) access it simultaneously.

**Kafka listener configuration:**
```
PLAINTEXT://kafka:9092       ← used by Spark (inside Docker network)
PLAINTEXT_HOST://localhost:29092  ← used by producers/dashboard (host machine)
```
Two listeners are required because Docker's internal DNS (`kafka`) resolves differently inside vs. outside the container network.

---

### 5.6 `hive-site.xml` — Hive Configuration

Overrides the container's default Hive configuration to point at the external PostgreSQL metastore. The file is bind-mounted into both `hive-metastore` and `hive-server` containers, ensuring both services use the same metastore database. Key properties:

- `javax.jdo.option.ConnectionURL` — JDBC URL to Postgres
- `hive.metastore.uris` — Thrift address for Spark to connect to
- `hive.server2.enable.doAs=false` — disables user impersonation (required in Docker where UIDs don't match)

---

## 6. Setup & Prerequisites

### 6.1 System Requirements

| Requirement | Recommended |
|---|---|
| RAM | 12 GB free (Docker containers are memory-hungry) |
| CPU | 4+ cores |
| Disk | 10 GB free for Docker images and HDFS data |
| OS | macOS, Linux, or Windows with WSL2 |
| Docker | Docker Desktop 4.x or Docker Engine 24+ |
| Python | 3.10 or 3.11 |

### 6.2 Install Docker and Docker Compose

```bash
# macOS (using Homebrew)
brew install --cask docker

# Verify
docker --version
docker compose version
```

On Linux, follow the [official Docker Engine install guide](https://docs.docker.com/engine/install/) and install the `docker-compose-plugin`.

### 6.3 Get an Alpaca API Key

1. Sign up at [https://app.alpaca.markets](https://app.alpaca.markets) (free paper-trading account)
2. Navigate to **API Keys** in the dashboard
3. Click **Generate New Key** — you receive an `API Key ID` and `Secret Key`
4. **Important:** Copy the secret immediately; Alpaca only shows it once

> The free Alpaca tier provides access to real-time IEX data. For full SIP (consolidated) data, a subscription is required. For this project, IEX data is sufficient.

### 6.4 Clone the Repository

```bash
git clone https://github.com/aneessaheba/realtime-market-analytics-kafka-spark-hive.git
cd realtime-market-analytics-kafka-spark-hive
```

### 6.5 Configure Environment Variables

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

```env
ALPACA_API_KEY=PKXXXXXXXXXXXXXXXXXX
ALPACA_API_SECRET=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
KAFKA_BROKER=localhost:29092
SYMBOLS=AAPL,TSLA,GOOGL,MSFT,AMZN
```

`.env` is listed in `.gitignore` and will never be committed.

### 6.6 Install Python Dependencies

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 6.7 Pull Docker Images

This step downloads ~8 GB of Docker images. Run it once in advance to avoid delays when starting the stack:

```bash
docker compose pull
```

---

## 7. Configuration

### 7.1 Kafka Topics

| Topic | Producer | Consumer | Description |
|---|---|---|---|
| `alpaca_trends` | `alpaca_producer.py` / `mock_producer.py` | `spark_trend_analyzer.py` | Raw preprocessed bar records |
| `alpaca_trend_results` | `spark_trend_analyzer.py` | `dashboard.py` | Windowed aggregates + trend signals |

Topics are auto-created by Kafka (`KAFKA_AUTO_CREATE_TOPICS_ENABLE=true`). No manual topic creation is required.

### 7.2 Spark Window Parameters

Configured in `spark_trend_analyzer.py`:

| Parameter | Value | Description |
|---|---|---|
| Window duration | 5 minutes | Each window covers 5 min of bar data |
| Slide duration | 1 minute | Windows are re-evaluated every 1 min |
| Watermark | 2 minutes | Late events within 2 min are still accepted |
| Hive trigger | Every 1 minute | How often Spark flushes Parquet to HDFS |

### 7.3 Dashboard Refresh

Set via `dcc.Interval(interval=5000)` in `dashboard.py`. Change the value (in milliseconds) to adjust refresh rate. Faster refresh uses more CPU; 5000ms is a good balance for streaming data.

### 7.4 Mock Producer Interval

Set `PUBLISH_INTERVAL = 5` in `mock_producer.py` (seconds between each round of publishing). Decrease to stress-test the pipeline; increase for lower-frequency simulation.

---

## 8. Running the Pipeline

> **All four steps run in separate terminal windows.** The order matters — infrastructure must be up before producers start, and Spark must be running before the dashboard has meaningful data.

### Step 1 — Start the Infrastructure

```bash
docker compose up -d
```

This starts all 10 services. Wait ~60–90 seconds for everything to become healthy. You can verify with:

```bash
docker compose ps
```

All services should show `Up` status. If `hive-metastore` keeps restarting, see [Troubleshooting](#101-hive-metastore-startup-failure).

**Useful service UIs once running:**

| Service | URL |
|---|---|
| Kafka (no UI by default) | `localhost:29092` |
| HDFS NameNode Web UI | http://localhost:50070 |
| Spark Master Web UI | http://localhost:8080 |
| Spark Worker Web UI | http://localhost:8081 |
| HiveServer2 | `localhost:10000` (Beeline/JDBC) |

### Step 2 — Start the Spark Trend Analyzer

The Spark job must be submitted into the running Spark container so it can resolve `kafka:9092` and `namenode:9000` via Docker's internal DNS:

```bash
docker exec -it spark-master /opt/spark/bin/spark-submit \
  --master spark://spark-master:7077 \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0 \
  /path/to/spark_trend_analyzer.py
```

> **Note on `--packages`:** The Kafka connector JAR is not bundled with the base Spark image. The `--packages` flag downloads it from Maven Central on first run. This requires internet access from inside the container. Subsequent runs use the cached JAR.

Alternatively, copy the script into the container first:

```bash
docker cp spark_trend_analyzer.py spark-master:/opt/spark/
docker exec -it spark-master /opt/spark/bin/spark-submit \
  --master spark://spark-master:7077 \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0 \
  /opt/spark/spark_trend_analyzer.py
```

You should see `Hive table 'default.stock_trends' ready.` and then `Streaming started. Waiting for data...`

### Step 3 — Start the Data Producer

**Option A: Live data (requires Alpaca API key)**
```bash
source venv/bin/activate
python alpaca_producer.py
```

Expected output:
```
2025-03-06 10:00:01 INFO Starting Alpaca real-time stream for: ['AAPL', 'TSLA', ...]
2025-03-06 10:00:05 INFO [AAPL] close=175.23 | change=+0.12% | dir=up | vol=124,500
```

**Option B: Mock data (no API key needed)**
```bash
source venv/bin/activate
python mock_producer.py
```

Expected output:
```
2025-03-06 10:00:01 INFO Mock producer started → topic 'alpaca_trends' every 5s
2025-03-06 10:00:06 INFO AAPL  | close=  175.30 | up   +0.17% | vol=  187,432 | bias=+0.0012
```

### Step 4 — Start the Dashboard

```bash
source venv/bin/activate
python dashboard.py
```

Open [http://localhost:8050](http://localhost:8050) in your browser. After one full 5-minute window of data accumulates, charts will begin populating. Signal badges appear as soon as the first Spark result arrives in the `alpaca_trend_results` topic.

### Stopping the Pipeline

```bash
# Stop producers and dashboard: Ctrl+C in each terminal

# Stop all Docker containers (preserves data volumes)
docker compose stop

# Stop and delete containers + volumes (full reset)
docker compose down -v
```

### Quick-Start Summary

```bash
# Terminal 1
docker compose up -d && docker compose ps

# Terminal 2 — Spark
docker cp spark_trend_analyzer.py spark-master:/opt/spark/
docker exec -it spark-master /opt/spark/bin/spark-submit \
  --master spark://spark-master:7077 \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0 \
  /opt/spark/spark_trend_analyzer.py

# Terminal 3 — Producer
source venv/bin/activate && python mock_producer.py

# Terminal 4 — Dashboard
source venv/bin/activate && python dashboard.py
# → open http://localhost:8050
```

---

## 9. Hive Queries & Monitoring

### 9.1 Connect to HiveServer2 with Beeline

```bash
docker exec -it hive-server /opt/hive/bin/beeline \
  -u jdbc:hive2://localhost:10000/default
```

### 9.2 Useful Hive Queries

**Check the table schema:**
```sql
DESCRIBE default.stock_trends;
```

**View the most recent trend windows:**
```sql
SELECT symbol, window_start, window_end,
       avg_close, trend_signal, buy_pressure, volatility
FROM default.stock_trends
ORDER BY window_start DESC
LIMIT 20;
```

**Most bullish symbol in the last hour:**
```sql
SELECT symbol,
       COUNT(*) AS bullish_windows,
       ROUND(AVG(avg_close), 2) AS mean_price,
       ROUND(AVG(buy_pressure) * 100, 1) AS avg_buy_pressure_pct
FROM default.stock_trends
WHERE trend_signal = 'BULLISH'
  AND window_start >= DATE_SUB(CURRENT_TIMESTAMP, 1)
GROUP BY symbol
ORDER BY bullish_windows DESC;
```

**Volatility comparison across symbols:**
```sql
SELECT symbol,
       ROUND(AVG(volatility), 4)   AS avg_volatility,
       ROUND(MAX(volatility), 4)   AS peak_volatility,
       ROUND(AVG(price_range), 4)  AS avg_price_range
FROM default.stock_trends
GROUP BY symbol
ORDER BY avg_volatility DESC;
```

**VWAP deviation over time (how far price drifted from fair value):**
```sql
SELECT symbol, window_start,
       ROUND(vwap_deviation_pct, 3) AS vwap_dev,
       trend_signal
FROM default.stock_trends
WHERE ABS(vwap_deviation_pct) > 0.1
ORDER BY ABS(vwap_deviation_pct) DESC
LIMIT 30;
```

**Count records stored (sanity check):**
```sql
SELECT symbol, COUNT(*) AS window_count
FROM default.stock_trends
GROUP BY symbol;
```

### 9.3 Check HDFS Parquet Files

```bash
# List files in the Hive warehouse
docker exec -it namenode hdfs dfs -ls /user/hive/warehouse/stock_trends/

# Check total size
docker exec -it namenode hdfs dfs -du -s -h /user/hive/warehouse/stock_trends/
```

### 9.4 Spark Streaming Monitoring

The Spark Master UI at **http://localhost:8080** shows:
- Running streaming jobs and their status
- Executor memory and CPU usage
- Processing time per micro-batch

In the Spark driver logs, each micro-batch prints a summary table to console showing the computed trend windows. You can also track streaming metrics via:

```bash
# Follow Spark driver logs
docker logs -f spark-master
```

### 9.5 Kafka Topic Inspection

```bash
# List all topics
docker exec -it kafka kafka-topics --bootstrap-server localhost:9092 --list

# Read raw messages from input topic
docker exec -it kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic alpaca_trends \
  --from-beginning \
  --max-messages 5

# Read Spark output (trend results)
docker exec -it kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic alpaca_trend_results \
  --from-beginning \
  --max-messages 5

# Check lag (how far behind consumers are)
docker exec -it kafka kafka-consumer-groups \
  --bootstrap-server localhost:9092 \
  --describe \
  --group dashboard_group
```

---

## 10. Technical Difficulties & Best Practices

This section documents every significant obstacle encountered during development and what was learned from each.

---

### 10.1 Hive Metastore Startup Failure

**Problem:** The `hive-metastore` container repeatedly restarted with errors like:
```
MetaException: Version information not found in metastore
```
or:
```
Unable to connect to JDBC metastore: hive-metastore-postgresql
```

**Root cause:** Two independent issues:
1. The `hive-metastore` container started before Postgres finished initialising its database schema.
2. The default Docker Hive image tries to use environment variables to configure the metastore, but the variable injection mechanism in older `bde2020/hive` images is broken for some settings.

**Solution:**
- Added `SERVICE_PRECONDITION: "namenode:50070 hive-metastore-postgresql:5432"` to the metastore service so it polls until both dependencies are actually listening on their ports before starting.
- Replaced environment variable-based Hive config entirely with a hand-crafted `hive-site.xml` bind-mounted into the container. This guarantees exact configuration regardless of image quirks.

**Best practice:** Never rely on Docker `depends_on` alone for services that need readiness checks. Use `SERVICE_PRECONDITION` or a health-check + `condition: service_healthy` in Compose to enforce actual readiness rather than just container-started state.

---

### 10.2 Kafka Listener Configuration — Two Listeners Required

**Problem:** Spark (running inside Docker) could not connect to Kafka, even though the host-machine producer worked fine. Error:
```
org.apache.kafka.common.errors.TimeoutException: Expiring 1 record(s) for alpaca_trends
```

**Root cause:** Kafka advertises its address to clients after they connect. When only `localhost:29092` was configured, Kafka advertised `localhost` to Spark — but inside Docker, `localhost` resolves to the Spark container itself, not the Kafka container.

**Solution:** Two separate listeners:
```
PLAINTEXT://kafka:9092           ← Docker-internal: "kafka" resolves via Docker DNS
PLAINTEXT_HOST://localhost:29092 ← Host machine: reaches Kafka via port mapping
```
Spark uses `kafka:9092`; the Python producers and dashboard use `localhost:29092`.

**Best practice:** When mixing host-machine and container clients for Kafka, always configure two listener protocols with distinct advertised addresses. Name them clearly (`PLAINTEXT` vs `PLAINTEXT_HOST`).

---

### 10.3 HDFS Directory Permissions for Hive

**Problem:** Spark's first write to the Hive warehouse failed:
```
org.apache.hadoop.security.AccessControlException: Permission denied:
user=root, access=WRITE, inode="/user/hive/warehouse"
```

**Root cause:** The HDFS `/user/hive/warehouse` directory did not exist. When `hive-server` tried to create it, the HDFS default umask prevented world-writable directories. Spark ran as `root` but the directory was owned by `hive`.

**Solution:** Added a dedicated `hdfs-init` one-shot container to the Docker Compose stack. It runs only once after the NameNode and DataNode are ready, creates the required directories, and sets permissions to `777`:
```bash
hdfs dfs -mkdir -p /user/hive/warehouse
hdfs dfs -chmod -R 777 /user/hive/warehouse
```

**Best practice:** Always initialise HDFS directories with explicit permissions before writing to them. In production, use proper POSIX ACLs or Ranger policies instead of `777`.

---

### 10.4 Hive DDL Type Mismatch — `LONG` vs `BIGINT`

**Problem:** The Hive `CREATE TABLE` statement used `LONG` as the data type for `bar_count`:
```sql
bar_count LONG
```
This caused a `ParseException` when Hive executed the DDL. `LONG` is a Java primitive but is **not a valid Hive type**.

**Solution:** Replaced with the correct Hive type:
```sql
bar_count BIGINT
```

**Best practice:** Hive's type system differs from Java's and Spark's. Always validate DDL statements directly in Beeline during development before embedding them in code.

---

### 10.5 Spark Kafka Connector JAR Not Bundled

**Problem:** Submitting `spark_trend_analyzer.py` failed immediately:
```
java.lang.ClassNotFoundException: org.apache.spark.sql.kafka010.KafkaSourceProvider
```

**Root cause:** The `apache/spark:3.5.0` base image does not include the Kafka structured-streaming connector. It must be provided separately.

**Solution:** Use `--packages` on the `spark-submit` command:
```bash
--packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0
```
Spark downloads the JAR from Maven Central on first run and caches it.

**Best practice:** For repeatable deployments, pre-download the JAR and mount it into the container, or build a custom Spark Docker image with the JAR pre-installed. Relying on Maven Central download at runtime introduces an external dependency that can fail.

---

### 10.6 Spark Structured Streaming Output Mode Constraints

**Problem:** Using `outputMode("complete")` with the Kafka and Hive sinks raised:
```
AnalysisException: Complete output mode not supported when there are no streaming aggregations
```
or silently wrote duplicate data.

**Root cause:** `complete` mode re-emits all rows every micro-batch. With Kafka and Parquet sinks, this causes unbounded Kafka message growth and Parquet file duplication. `update` mode only re-emits changed rows, which is what we want for streaming aggregations.

**Solution:**
- Kafka sink: `outputMode("update")` — only changed windows are re-published
- Hive/Parquet sink: `outputMode("append")` with a watermark — only finalised (past the watermark) windows are written, preventing overwrites

**Best practice:** Match output mode carefully to the sink semantics. `update` is generally correct for Kafka; `append` (with watermark) is correct for storage sinks to avoid duplicates.

---

### 10.7 Watermark Tuning for Late Data

**Problem:** Early in testing, some bars arrived slightly late (network jitter from the Alpaca WebSocket), and those bars were silently dropped by Spark rather than included in their window.

**Root cause:** The watermark was initially set to 0 (no late tolerance). Any event with an `event_time` more than 0 seconds behind the watermark was discarded.

**Solution:** Increased watermark to 2 minutes:
```python
df.withWatermark("event_time", "2 minutes")
```
This allows events arriving up to 2 minutes late to still be included in their correct window.

**Best practice:** Set watermark based on observed end-to-end latency in your environment. Too tight → data loss. Too loose → state accumulates in memory and checkpoints grow large. 2 minutes is a safe starting point for low-latency WebSocket sources.

---

### 10.8 API Keys in Source Code

**Problem:** Initial versions of `alpaca_producer.py` hardcoded credentials:
```python
API_KEY = "PK..."
API_SECRET = "..."
```
Committing this to a public GitHub repository would expose the credentials to anyone who views the repo, and revoke them immediately via GitHub's secret scanning.

**Solution:**
- Moved all secrets to `.env` (listed in `.gitignore`)
- Added `.env.example` with placeholder values so contributors know what variables are needed
- Use `python-dotenv` to load them at runtime

**Best practice:** Never hardcode credentials in source code. Use environment variables, a secrets manager, or a `.env` file that is explicitly excluded from version control. Rotate any key that was ever committed, even briefly.

---

### 10.9 Docker Resource Limits on macOS

**Problem:** Docker Desktop on macOS defaulted to 2 GB RAM, causing the NameNode, HiveServer2, and Spark containers to OOM-kill each other.

**Solution:** In Docker Desktop → Settings → Resources, increase RAM to at least **12 GB** and CPUs to **4**. The full stack comfortably fits in 10–12 GB.

**Best practice:** Always document minimum resource requirements for containerised big data stacks. For lighter development, run only the services you need:
```bash
docker compose up -d zookeeper kafka  # just Kafka
docker compose up -d namenode datanode hdfs-init  # just HDFS
```

---

### 10.10 Alpaca WebSocket Connection Drops During Market Hours

**Problem:** The Alpaca WebSocket stream occasionally disconnected after 30–60 minutes with no error, silently stopping data flow.

**Root cause:** Alpaca's streaming infrastructure closes idle or stale connections. If the local network has NAT timeout rules shorter than Alpaca's keepalive interval, the connection drops silently.

**Solution:** Added an outer retry loop in `alpaca_producer.py` that catches any exception from `stream.run()` and reconnects after a `RETRY_DELAY` (default 10 seconds), up to `MAX_RETRIES` attempts.

**Best practice:** All persistent WebSocket/streaming connections in production should have reconnection logic. Treat connection loss as a normal event, not an error condition.

---

## 11. Learning Summary & Reflections

### 11.1 What We Learned

**Apache Kafka**
Kafka is not just a message queue — it is a distributed, durable, ordered log. The key insight is that Kafka topics can serve simultaneously as a pipeline transport (producer → Spark) and as a real-time API (Spark → dashboard). The decoupling this provides is profound: the dashboard does not need to know about Spark at all; it just reads from a topic. We also learned that Kafka's partitioning strategy is critical for Spark — keying messages by symbol ensures Spark can consume each symbol's stream in order, which matters for accurate window computations.

**PySpark Structured Streaming**
Structured Streaming's event-time processing model is fundamentally different from micro-batch RDD processing. The watermark-window combination is elegant but requires careful tuning — getting it wrong either loses late data (watermark too tight) or accumulates unbounded state (watermark too loose). The fact that Spark Streaming integrates seamlessly with the Hive metastore via `enableHiveSupport()` — writing Parquet to HDFS paths that Hive can immediately query — was a major insight into how the Hadoop ecosystem is designed to compose.

**Apache Hive on HDFS**
Hive is a translation layer: you write SQL, it generates MapReduce or Tez jobs. For streaming pipelines, Hive is most useful as the **read layer** — Spark writes Parquet files to HDFS, and Hive makes those files instantly queryable via standard SQL. We learned that Hive's type system has subtle differences from Spark's (e.g., `BIGINT` not `LONG`, `FLOAT` not `REAL`), and that the Postgres-backed metastore is vastly more reliable than the default Derby embedded database.

**Docker Compose for Big Data**
Orchestrating 10 containers with interdependencies taught us a great deal about service readiness, networking, and resource management. The biggest realisation was that `depends_on` in Docker Compose only waits for a container to *start*, not for the service inside it to become *ready*. For big data stacks where services like HiveServer2 can take 30+ seconds to initialise, this distinction is critical.

**Plotly Dash for Real-Time Visualization**
Dash bridges the gap between Python data processing and interactive web dashboards without requiring JavaScript. The threading model — Kafka consumer in a background thread, Dash callbacks in the main thread, shared state protected by a lock — is a clean and practical pattern for live data dashboards. One limitation is that Dash's update interval is polling-based rather than event-driven; for true push-based updates, WebSocket integration or Server-Sent Events would be needed.

---

### 11.2 Challenges Faced

| Challenge | Impact | Resolution |
|---|---|---|
| Hive metastore startup race condition | High — blocked all Hive operations | `SERVICE_PRECONDITION` health polling |
| Kafka dual-listener configuration | High — Spark couldn't connect to Kafka | Two listener protocols configured |
| HDFS permission denied for Hive warehouse | High — no data could be stored | `hdfs-init` one-shot container |
| Hive DDL `LONG` type error | Medium — table creation failed | Changed to `BIGINT` |
| Spark Kafka JAR missing | Medium — Spark job wouldn't start | `--packages` on spark-submit |
| Docker RAM exhaustion on Mac | Medium — OOM kills of containers | Raised Docker Desktop memory limit |
| Alpaca WebSocket silent disconnects | Medium — data stream silently stopped | Retry loop with exponential backoff |
| Output mode mismatch with sinks | Low — duplicate Parquet files | Switched to `append` with watermark |
| API keys in source code | Security risk | Moved to `.env` + `python-dotenv` |
| Late event data loss | Low — minor inaccuracy | Watermark increased to 2 minutes |

---

### 11.3 Insights Gained

**On streaming vs. batch:**
Real-time streaming is fundamentally harder than batch processing because you cannot see the full dataset before computing. Windowing, watermarks, and output modes are all compensations for this fundamental uncertainty. Batch processing's luxury of global knowledge is entirely absent in streaming.

**On the value of decoupling:**
The most powerful design decision in this pipeline is the use of Kafka as a buffer between every stage. Because each component only knows about its Kafka topics, any stage can be replaced, upgraded, or scaled independently. This is the core value proposition of a streaming pipeline over point-to-point integrations.

**On the complexity of distributed systems:**
Getting 10 containers to start in the right order, with correct network connectivity, correct filesystem permissions, and correct configuration — all on a laptop — gave a concrete appreciation for why production Hadoop clusters require dedicated infrastructure teams. Tools like Kubernetes, Helm charts, and managed cloud services (Confluent Cloud, AWS MSK, Databricks) exist precisely to abstract away this operational complexity.

**On the Alpaca API:**
Alpaca provides a free, real-time market data stream with a clean Python SDK. The bar data structure (OHLCV + VWAP) is rich enough to compute meaningful technical indicators. The WebSocket approach is far better than polling a REST API for real-time data — it eliminates API rate-limit concerns and reduces latency.

**On metric design:**
The `buy_pressure` metric (fraction of up-ticks) proved surprisingly informative. When combined with `volatility` and `vwap_deviation_pct`, it creates a multi-dimensional view of market state. A stock with high buy pressure and low VWAP deviation is accumulating quietly; high buy pressure with high VWAP deviation suggests momentum overbought conditions.

---

## 12. Future Improvements

| Feature | Description | Priority |
|---|---|---|
| RSI indicator | Implement 14-period Relative Strength Index in Spark | High |
| Moving averages | EMA-20 and SMA-50 for trend confirmation | High |
| Alert system | Kafka-based alert topic: push BULLISH/BEARISH signal changes to email or Slack | Medium |
| Historical backfill | Use Alpaca's REST bars endpoint to seed Hive with 1-year historical data for context | Medium |
| Grafana dashboard | Replace Plotly Dash with Grafana + Kafka data source for richer charting and alerting | Medium |
| Schema Registry | Add Confluent Schema Registry to enforce Avro schemas on Kafka topics | Medium |
| Kubernetes deployment | Convert Docker Compose to Helm chart for cloud deployment (GKE, EKS) | Low |
| Unit tests | Add pytest tests for `preprocess_bar()` and `compute_trends()` logic | Medium |
| Sentiment overlay | Integrate Reddit/Twitter sentiment (VADER or BERT) alongside price trends | Low |
| Portfolio simulation | Track simulated P&L from acting on BULLISH/BEARISH signals | Low |
| Flink alternative | Re-implement the Spark job in Apache Flink for lower-latency event processing | Low |

---

*Built for DATA 228 — Big Data Technologies, San Jose State University.*
*Author: Aneessa Heba Guddi*
