import json
import time
import random
import logging
from datetime import datetime, timezone
from kafka import KafkaProducer

# Kafka config
KAFKA_BROKER     = "localhost:29092"
KAFKA_TOPIC      = "alpaca_trends"
PUBLISH_INTERVAL = 5

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BASE_PRICES = {
    "AAPL":  175.0,
    "TSLA":  250.0,
    "GOOGL": 140.0,
    "MSFT":  380.0,
    "AMZN":  185.0,
}

current_prices = dict(BASE_PRICES)


def simulate_bar(symbol):
    price = current_prices[symbol]

    change_pct = random.uniform(-0.005, 0.005)
    close = round(price * (1 + change_pct), 2)
    open_ = round(price * (1 + random.uniform(-0.002, 0.002)), 2)
    high  = round(max(open_, close) * (1 + random.uniform(0, 0.003)), 2)
    low   = round(min(open_, close) * (1 - random.uniform(0, 0.003)), 2)
    vol   = random.randint(50_000, 500_000)
    vwap  = round((high + low + close) / 3, 2)

    price_change = round(close - open_, 4)
    pct_change   = round((price_change / open_) * 100, 4) if open_ != 0 else 0

    if price_change > 0:
        direction = "up"
    elif price_change < 0:
        direction = "down"
    else:
        direction = "flat"

    current_prices[symbol] = close

    return {
        "symbol":       symbol,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "open":         open_,
        "high":         high,
        "low":          low,
        "close":        close,
        "volume":       vol,
        "vwap":         vwap,
        "price_change": price_change,
        "pct_change":   pct_change,
        "direction":    direction,
        "ingested_at":  datetime.utcnow().isoformat(),
    }


def main():
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8"),
    )

    log.info(f"Mock producer started → topic '{KAFKA_TOPIC}' every {PUBLISH_INTERVAL}s")
    log.info("Press Ctrl+C to stop.\n")

    try:
        while True:
            for symbol in BASE_PRICES:
                bar = simulate_bar(symbol)
                producer.send(KAFKA_TOPIC, key=bar["symbol"], value=bar)
                log.info(
                    f"{bar['symbol']:5s} | close={bar['close']:>8.2f} "
                    f"| {bar['direction']:4s} {bar['pct_change']:+.2f}% "
                    f"| vol={bar['volume']:>8,}"
                )
            producer.flush()
            print("─" * 60)
            time.sleep(PUBLISH_INTERVAL)
    except KeyboardInterrupt:
        log.info("Mock producer stopped.")
    finally:
        producer.close()


if __name__ == "__main__":
    main()