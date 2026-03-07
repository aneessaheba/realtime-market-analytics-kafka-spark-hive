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
