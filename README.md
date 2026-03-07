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
