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

# Each symbol independently drifts with a slowly-changing trend bias.
# Positive bias → more likely to tick up; negative → more likely to tick down.
# The bias reverses when price drifts too far from the base, creating realistic
# mean-reversion cycles.
trend_bias = {sym: random.uniform(-0.001, 0.001) for sym in BASE_PRICES}
BIAS_SHIFT_INTERVAL = 10   # number of publish rounds before bias can shift
_round_counter = 0


def _update_biases():
    """Randomly walk the trend bias for each symbol."""
    for sym in trend_bias:
        deviation = (current_prices[sym] - BASE_PRICES[sym]) / BASE_PRICES[sym]
        # Mean-reversion: push bias back toward 0 if price drifted >3%
        if abs(deviation) > 0.03:
            trend_bias[sym] = -deviation * 0.1
        else:
            trend_bias[sym] += random.uniform(-0.0005, 0.0005)
        # Clamp bias to a sensible range
        trend_bias[sym] = max(-0.003, min(0.003, trend_bias[sym]))


def simulate_bar(symbol):
    price = current_prices[symbol]
    bias  = trend_bias[symbol]

    change_pct = random.uniform(-0.005, 0.005) + bias
    close = round(price * (1 + change_pct), 2)
    open_ = round(price * (1 + random.uniform(-0.002, 0.002)), 2)
    high  = round(max(open_, close) * (1 + random.uniform(0, 0.003)), 2)
    low   = round(min(open_, close) * (1 - random.uniform(0, 0.003)), 2)

    # Volume spikes when bias is strong (simulates momentum-driven trading)
    base_vol = random.randint(50_000, 300_000)
    vol_multiplier = 1 + abs(bias) * 200
    vol = int(base_vol * vol_multiplier)

    vwap = round((high + low + close) / 3, 2)

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
    global _round_counter

    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8"),
    )

    log.info(f"Mock producer started → topic '{KAFKA_TOPIC}' every {PUBLISH_INTERVAL}s")
    log.info("Press Ctrl+C to stop.\n")

    try:
        while True:
            _round_counter += 1
            if _round_counter % BIAS_SHIFT_INTERVAL == 0:
                _update_biases()

            for symbol in BASE_PRICES:
                bar = simulate_bar(symbol)
                producer.send(KAFKA_TOPIC, key=bar["symbol"], value=bar)
                log.info(
                    f"{bar['symbol']:5s} | close={bar['close']:>8.2f} "
                    f"| {bar['direction']:4s} {bar['pct_change']:+.2f}% "
                    f"| vol={bar['volume']:>8,} "
                    f"| bias={trend_bias[symbol]:+.4f}"
                )
            producer.flush()
            print("─" * 70)
            time.sleep(PUBLISH_INTERVAL)
    except KeyboardInterrupt:
        log.info("Mock producer stopped.")
    finally:
        producer.close()


if __name__ == "__main__":
    main()
