import json
from datetime import datetime
from alpaca.data.live import StockDataStream
from kafka import KafkaProducer

API_KEY = "YOUR_API_KEY"
API_SECRET = "YOUR_API_SECRET"

SYMBOLS = ["AAPL", "TSLA", "GOOGL", "MSFT", "AMZN"]

KAFKA_BROKER = "localhost:29092"
KAFKA_TOPIC  = "alpaca_trends"

producer = KafkaProducer(
    bootstrap_servers=KAFKA_BROKER,
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    key_serializer=lambda k: k.encode("utf-8"),
)

def preprocess_bar(bar):
    try:
        if bar is None:
            return None

        open_price  = float(bar.open)
        close_price = float(bar.close)
        high_price  = float(bar.high)
        low_price   = float(bar.low)
        volume      = int(bar.volume) if bar.volume else 0
        vwap        = float(bar.vwap) if hasattr(bar, "vwap") and bar.vwap else None

        price_change = close_price - open_price
        pct_change   = (price_change / open_price) * 100 if open_price != 0 else 0

        if price_change > 0:
            direction = "up"
        elif price_change < 0:
            direction = "down"
        else:
            direction = "flat"

        clean_record = {
            "symbol":       bar.symbol,
            "timestamp":    bar.timestamp.isoformat() if bar.timestamp else datetime.utcnow().isoformat(),
            "open":         round(open_price,  4),
            "high":         round(high_price,  4),
            "low":          round(low_price,   4),
            "close":        round(close_price, 4),
            "volume":       volume,
            "vwap":         round(vwap, 4) if vwap else None,
            "price_change": round(price_change, 4),
            "pct_change":   round(pct_change,   4),
            "direction":    direction,
            "ingested_at":  datetime.utcnow().isoformat(),
        }

        return clean_record

    except Exception as e:
        print("Preprocessing error:", e)
        return None


async def handle_bar(bar):
    record = preprocess_bar(bar)

    if record:
        print(f"[{record['symbol']}] close={record['close']} "
              f"| change={record['pct_change']:+.2f}% "
              f"| dir={record['direction']} "
              f"| vol={record['volume']:,}")

        producer.send(KAFKA_TOPIC, key=record["symbol"], value=record)
        producer.flush()


def main():
    print(f"Starting Alpaca real-time stream for: {SYMBOLS}")
    print(f"Publishing to Kafka topic: {KAFKA_TOPIC}")

    stream = StockDataStream(API_KEY, API_SECRET)
    stream.subscribe_bars(handle_bar, *SYMBOLS)

    try:
        stream.run()
    except KeyboardInterrupt:
        print("Stream stopped.")
        producer.close()


if __name__ == "__main__":
    main()