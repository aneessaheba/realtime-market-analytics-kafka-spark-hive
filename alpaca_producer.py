import json
import logging
import os
import time
from datetime import datetime

from alpaca.data.live import StockDataStream
from dotenv import load_dotenv
from kafka import KafkaProducer

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

API_KEY    = os.environ.get("ALPACA_API_KEY",    "YOUR_API_KEY")
API_SECRET = os.environ.get("ALPACA_API_SECRET", "YOUR_API_SECRET")

KAFKA_BROKER = os.environ.get("KAFKA_BROKER", "localhost:29092")
KAFKA_TOPIC  = "alpaca_trends"

_symbols_env = os.environ.get("SYMBOLS", "AAPL,TSLA,GOOGL,MSFT,AMZN")
SYMBOLS = [s.strip() for s in _symbols_env.split(",") if s.strip()]

RETRY_DELAY = 10   # seconds between reconnect attempts
MAX_RETRIES = 5


def make_producer():
    return KafkaProducer(
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
        log.error("Preprocessing error: %s", e)
        return None


async def handle_bar(bar):
    record = preprocess_bar(bar)

    if record:
        log.info(
            "[%s] close=%.2f | change=%+.2f%% | dir=%s | vol=%s",
            record["symbol"], record["close"],
            record["pct_change"], record["direction"],
            f"{record['volume']:,}",
        )
        producer.send(KAFKA_TOPIC, key=record["symbol"], value=record)
        producer.flush()


def main():
    global producer
    log.info("Starting Alpaca real-time stream for: %s", SYMBOLS)
    log.info("Publishing to Kafka topic: %s on broker %s", KAFKA_TOPIC, KAFKA_BROKER)

    producer = make_producer()

    attempt = 0
    while True:
        try:
            attempt += 1
            log.info("Stream attempt %d …", attempt)
            stream = StockDataStream(API_KEY, API_SECRET)
            stream.subscribe_bars(handle_bar, *SYMBOLS)
            stream.run()
        except KeyboardInterrupt:
            log.info("Stream stopped by user.")
            producer.close()
            break
        except Exception as exc:
            log.warning("Stream error: %s", exc)
            if MAX_RETRIES and attempt >= MAX_RETRIES:
                log.error("Max retries (%d) reached. Exiting.", MAX_RETRIES)
                producer.close()
                break
            log.info("Reconnecting in %ds …", RETRY_DELAY)
            time.sleep(RETRY_DELAY)


if __name__ == "__main__":
    main()
