import json
import threading
import pandas as pd
from collections import defaultdict, deque
from kafka import KafkaConsumer
import dash
from dash import dcc, html
from dash.dependencies import Input, Output
import plotly.graph_objects as go

KAFKA_BROKER = "localhost:29092"
KAFKA_TOPIC  = "alpaca_trend_results"

MAX_POINTS = 50

SIGNAL_COLORS = {
    "BULLISH": "#00cc96",
    "BEARISH": "#ef553b",
    "NEUTRAL": "#636efa"
}

data_store = defaultdict(lambda: deque(maxlen=MAX_POINTS))
store_lock = threading.Lock()


def kafka_consumer_thread():
    consumer = KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="latest",
        enable_auto_commit=True,
        group_id="dashboard_group",
    )
    print(f"Dashboard listening on '{KAFKA_TOPIC}'...")
    for msg in consumer:
        record = msg.value
        symbol = record.get("symbol")
        if symbol:
            with store_lock:
                data_store[symbol].append(record)


def get_snapshot():
    with store_lock:
        return {sym: list(recs) for sym, recs in data_store.items()}


threading.Thread(target=kafka_consumer_thread, daemon=True).start()

app = dash.Dash(__name__)
app.title = "Alpaca Real-Time Trend Dashboard"

app.layout = html.Div(
    style={"backgroundColor": "#1a1a2e", "fontFamily": "Arial", "padding": "20px"},
    children=[
        html.H1(
            "Alpaca Real-Time Trend Analyzer",
            style={"color": "#e0e0e0", "textAlign": "center"}
        ),
        html.Div(id="signal-badges", style={"textAlign": "center", "marginBottom": "20px"}),
        dcc.Graph(id="price-chart",       style={"marginBottom": "20px"}),
        dcc.Graph(id="ohlc-chart",        style={"marginBottom": "20px"}),
        dcc.Graph(id="buy-pressure-chart",style={"marginBottom": "20px"}),
        dcc.Graph(id="volatility-chart",  style={"marginBottom": "20px"}),
        dcc.Graph(id="volume-chart"),
        dcc.Interval(id="interval", interval=5000, n_intervals=0),
    ],
)


def empty_figure(message="Waiting for data..."):
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor="#16213e",
        plot_bgcolor="#16213e",
        font_color="#e0e0e0",
        annotations=[{"text": message, "showarrow": False,
                      "font": {"size": 20, "color": "#aaaaaa"}}]
    )
    return fig


def base_layout(title, xaxis_title, yaxis_title):
    return dict(
        title=title,
        paper_bgcolor="#16213e",
        plot_bgcolor="#16213e",
        font_color="#e0e0e0",
        legend_bgcolor="#16213e",
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
    )


@app.callback(
    Output("signal-badges",    "children"),
    Output("price-chart",      "figure"),
    Output("ohlc-chart",       "figure"),
    Output("buy-pressure-chart","figure"),
    Output("volatility-chart", "figure"),
    Output("volume-chart",     "figure"),
    Input("interval",          "n_intervals"),
)
def update_dashboard(_):
    snapshot = get_snapshot()

    if not snapshot:
        empty = empty_figure()
        return [], empty, empty, empty, empty, empty

    # --- Signal badges ---
    badges = []
    for sym, recs in snapshot.items():
        if recs:
            latest = recs[-1]
            signal = latest.get("trend_signal", "NEUTRAL")
            color  = SIGNAL_COLORS.get(signal, "#636efa")
            bp     = latest.get("buy_pressure", 0)
            badges.append(html.Span(
                f" {sym}: {signal} | ${latest.get('avg_close', 0):.2f} | BP {bp:.0%} ",
                style={
                    "backgroundColor": color,
                    "color": "white",
                    "borderRadius": "8px",
                    "padding": "6px 14px",
                    "margin": "4px",
                    "fontWeight": "bold",
                    "fontSize": "14px",
                },
            ))

    # --- Avg close price line chart ---
    price_fig = go.Figure()
    for sym, recs in snapshot.items():
        if recs:
            df = pd.DataFrame(recs)
            price_fig.add_trace(go.Scatter(
                x=df["window_start"], y=df["avg_close"],
                mode="lines+markers", name=sym, line={"width": 2},
            ))
    price_fig.update_layout(**base_layout(
        "Average Close Price per Window", "Window", "Price (USD)"
    ))

    # --- OHLC box chart using min/avg/max close per window ---
    ohlc_fig = go.Figure()
    for sym, recs in snapshot.items():
        if recs:
            df = pd.DataFrame(recs)
            ohlc_fig.add_trace(go.Box(
                name=sym,
                q1=df["min_close"],
                median=df["avg_close"],
                q3=df["max_close"],
                lowerfence=df["min_close"],
                upperfence=df["max_close"],
                mean=df["avg_close"],
                showlegend=True,
            ))
    ohlc_fig.update_layout(**base_layout(
        "Price Range per Window (min / avg / max close)", "Symbol", "Price (USD)"
    ))

    # --- Buy pressure chart ---
    bp_fig = go.Figure()
    for sym, recs in snapshot.items():
        if recs:
            df = pd.DataFrame(recs)
            if "buy_pressure" in df.columns:
                bp_fig.add_trace(go.Scatter(
                    x=df["window_start"], y=df["buy_pressure"] * 100,
                    mode="lines+markers", name=sym, line={"width": 2},
                ))
    bp_fig.add_hline(y=50, line_dash="dot", line_color="gray",
                     annotation_text="50% neutral", annotation_position="bottom right")
    bp_fig.update_layout(**base_layout(
        "Buy Pressure % per Window (>50% = more up-ticks)", "Window", "Buy Pressure (%)"
    ))

    # --- Volatility bar chart ---
    vol_fig = go.Figure()
    for sym, recs in snapshot.items():
        if recs:
            df = pd.DataFrame(recs)
            vol_fig.add_trace(go.Bar(
                x=df["window_start"], y=df["volatility"], name=sym,
            ))
    vol_fig.update_layout(barmode="group", **base_layout(
        "Price Volatility (StdDev) per Window", "Window", "Volatility"
    ))

    # --- Average volume line chart ---
    volume_fig = go.Figure()
    for sym, recs in snapshot.items():
        if recs:
            df = pd.DataFrame(recs)
            volume_fig.add_trace(go.Scatter(
                x=df["window_start"], y=df["avg_volume"],
                mode="lines+markers", name=sym,
                line={"width": 2, "dash": "dot"},
            ))
    volume_fig.update_layout(**base_layout(
        "Average Volume per Window", "Window", "Volume"
    ))

    return badges, price_fig, ohlc_fig, bp_fig, vol_fig, volume_fig


def main():
    print("Dashboard running at http://localhost:8050")
    app.run(debug=False, host="0.0.0.0", port=8050)


if __name__ == "__main__":
    main()
