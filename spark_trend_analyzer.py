import sys
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, from_json, to_json, struct, window,
    avg, max, min, stddev, count,
    when, round as spark_round
)
from pyspark.sql.types import (
    StructType, StructField, StringType,
    DoubleType, LongType, TimestampType
)

KAFKA_BROKER = "kafka:9092"
INPUT_TOPIC  = "alpaca_trends"
OUTPUT_TOPIC = "alpaca_trend_results"

HIVE_TABLE         = "default.stock_trends"
CHECKPOINT_DIR     = "/tmp/spark_checkpoints/trend_analyzer"
HIVE_WAREHOUSE_DIR = "hdfs://namenode:9000/user/hive/warehouse"

RAW_SCHEMA = StructType([
    StructField("symbol",       StringType(), True),
    StructField("timestamp",    StringType(), True),
    StructField("open",         DoubleType(), True),
    StructField("high",         DoubleType(), True),
    StructField("low",          DoubleType(), True),
    StructField("close",        DoubleType(), True),
    StructField("volume",       LongType(),   True),
    StructField("vwap",         DoubleType(), True),
    StructField("price_change", DoubleType(), True),
    StructField("pct_change",   DoubleType(), True),
    StructField("direction",    StringType(), True),
    StructField("ingested_at",  StringType(), True),
])


def create_spark_session():
    return (
        SparkSession.builder
        .appName("AlpacaTrendAnalyzer")
        .config("spark.sql.warehouse.dir", HIVE_WAREHOUSE_DIR)
        .config("hive.metastore.uris", "thrift://hive-metastore:9083")
        .config("spark.sql.streaming.checkpointLocation", CHECKPOINT_DIR)
        .enableHiveSupport()
        .getOrCreate()
    )


def read_from_kafka(spark):
    return (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BROKER)
        .option("subscribe", INPUT_TOPIC)
        .option("startingOffsets", "latest")
        .load()
        .selectExpr("CAST(value AS STRING) as raw_value")
        .select(from_json(col("raw_value"), RAW_SCHEMA).alias("data"))
        .select("data.*")
        .withColumn("event_time", col("timestamp").cast(TimestampType()))
    )


def compute_trends(df):
    return (
        df.withWatermark("event_time", "2 minutes")
        .groupBy(
            window(col("event_time"), "5 minutes", "1 minute"),
            col("symbol")
        )
        .agg(
            spark_round(avg("close"),    4).alias("avg_close"),
            spark_round(max("close"),    4).alias("max_close"),
            spark_round(min("close"),    4).alias("min_close"),
            spark_round(avg("volume"),   0).alias("avg_volume"),
            spark_round(stddev("close"), 4).alias("volatility"),
            count("*").alias("bar_count"),
        )
        .withColumn("price_range", spark_round(col("max_close") - col("min_close"), 4))
        .withColumn(
            "trend_signal",
            when(col("avg_close") > col("min_close") + (col("price_range") * 0.6), "BULLISH")
            .when(col("avg_close") < col("min_close") + (col("price_range") * 0.4), "BEARISH")
            .otherwise("NEUTRAL")
        )
        .withColumn("window_start", col("window.start").cast(StringType()))
        .withColumn("window_end",   col("window.end").cast(StringType()))
        .drop("window")
    )


def write_to_console(df):
    return (
        df.writeStream
        .format("console")
        .option("truncate", False)
        .outputMode("update")
        .start()
    )


def write_to_kafka(df):
    return (
        df.select(
            col("symbol").alias("key"),
            to_json(struct("*")).alias("value")
        )
        .writeStream
        .format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BROKER)
        .option("topic", OUTPUT_TOPIC)
        .option("checkpointLocation", f"{CHECKPOINT_DIR}/kafka_sink")
        .outputMode("update")
        .start()
    )


def write_to_hive(df):
    return (
        df.writeStream
        .format("parquet")
        .option("path", f"{HIVE_WAREHOUSE_DIR}/{HIVE_TABLE.replace('.', '/')}")
        .option("checkpointLocation", f"{CHECKPOINT_DIR}/hive_sink")
        .outputMode("append")
        .trigger(processingTime="1 minute")
        .start()
    )


def ensure_hive_table(spark):
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS {HIVE_TABLE} (
            symbol       STRING,
            window_start STRING,
            window_end   STRING,
            avg_close    DOUBLE,
            max_close    DOUBLE,
            min_close    DOUBLE,
            avg_volume   DOUBLE,
            volatility   DOUBLE,
            bar_count    BIGINT,
            price_range  DOUBLE,
            trend_signal STRING
        )
        STORED AS PARQUET
    """)
    print(f"Hive table '{HIVE_TABLE}' ready.")


def main():
    spark = create_spark_session()
    spark.sparkContext.setLogLevel("WARN")

    ensure_hive_table(spark)

    raw_df    = read_from_kafka(spark)
    trends_df = compute_trends(raw_df)

    write_to_console(trends_df)
    write_to_kafka(trends_df)
    write_to_hive(trends_df)

    print("Streaming started. Waiting for data...")
    spark.streams.awaitAnyTermination()


if __name__ == "__main__":
    main()