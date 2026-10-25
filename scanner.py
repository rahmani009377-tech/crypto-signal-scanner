import json
import re
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo('Asia/Kabul')

SPOT_API = "https://data-api.binance.vision/api/v3/ticker/24hr"
SPOT_KLINES_API = "https://data-api.binance.vision/api/v3/klines"

# Conservative defaults: prioritize liquid pairs and avoid chasing late daily pumps.
MIN_VOLUME_USDT = 3_000_000
MIN_CHANGE_24H = 3.0
MAX_BULLISH_CHANGE_24H = 18.0
MAX_15M_CHANGE = 3.5
MAX_1H_CHANGE = 7.0
VALID_MINUTES = 15
MAX_SIGNALS_PER_MARKET = 30
MAX_CONFIRMED_SPOT_SIGNALS = 2
MAX_TOP_10_SIGNALS = 10
TIMEFRAMES = ("15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d")
MIN_BULLISH_TIMEFRAMES = 5


def get_data(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; CryptoSignalScanner/1.0)",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = response.read().decode("utf-8", errors="replace")
            if not body.strip():
                raise RuntimeError(f"Empty response; HTTP status={response.status}")
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                raise RuntimeError(
                    f"Invalid JSON; HTTP status={response.status}; body={body[:200]!r}"
                )
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code}; body={body[:200]!r}")


def build_signals(data, market_type, now):
    results = []

    for coin in data:
        symbol = coin.get("symbol", "")
        # Keep ordinary ASCII USDT pairs; ignore malformed or nonstandard symbols.
        if not re.fullmatch(r"[A-Z0-9]+USDT", symbol):
            continue

        try:
            price = float(coin["lastPrice"])
            change = float(coin["priceChangePercent"])
            volume = float(coin["quoteVolume"])
            if price <= 0 or volume < MIN_VOLUME_USDT:
                continue

            if change >= MIN_CHANGE_24H:
                direction = "BULLISH"
                # Exclude extreme 24h pumps before ranking so they cannot crowd out cleaner setups.
                if change > MAX_BULLISH_CHANGE_24H:
                    continue
            elif change <= -MIN_CHANGE_24H:
                direction = "BEARISH"
            else:
                continue

            results.append({
                "symbol": symbol,
                "market_type": market_type,
                "price": price,
                "change_24h": change,
                "volume_usdt": volume,
                "direction": direction,
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=VALID_MINUTES)).isoformat(),
                "status": "CANDIDATE_NOT_CONFIRMED",
            })
        except (ValueError, KeyError, TypeError):
            continue

    # For spot trading, prioritize bullish candidates before bearish avoid-buy context.
    # Within each direction, sort by the magnitude of the 24-hour move.
    results.sort(
        key=lambda item: (
            item["direction"] != "BULLISH",
            -abs(item["change_24h"]),
        )
    )
    return results[:MAX_SIGNALS_PER_MARKET]


def get_trend(symbol, interval):
    """Analyze closed candles individually; the currently forming candle is excluded."""
    url = f"{SPOT_KLINES_API}?symbol={symbol}&interval={interval}&limit=41"
    candles = get_data(url)
    if not isinstance(candles, list) or len(candles) < 22:
        raise RuntimeError(f"Not enough {interval} candles for {symbol}")
    closed = candles[:-1]
    normalized = []
    for candle in closed:
        try:
            opened, high, low, close = (float(candle[i]) for i in (1, 2, 3, 4))
            base_volume = float(candle[5])
            quote_volume = float(candle[7]) if len(candle) > 7 else 0.0
        except (ValueError, TypeError, IndexError):
            raise RuntimeError(f"Malformed {interval} candle for {symbol}")
        if min(opened, high, low, close) <= 0 or high < max(opened, close, low) or low > min(opened, close, high):
            raise RuntimeError(f"Invalid OHLC values in {interval} candle for {symbol}")
        normalized.append({
            "open_time": datetime.fromtimestamp(float(candle[0]) / 1000, timezone.utc).isoformat(),
            "open": opened, "high": high, "low": low, "close": close,
            "volume": base_volume, "quote_volume_usdt": quote_volume,
        })
    last = normalized[-1]
    previous = normalized[-2]
    lookback_close = normalized[-4]["close"]
    change_pct = (last["close"] / lookback_close - 1.0) * 100.0
    if last["close"] > previous["close"] and change_pct > 0:
        direction = "BULLISH"
    elif last["close"] < previous["close"] and change_pct < 0:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    true_ranges = []
    for index, candle in enumerate(normalized):
        previous_close = normalized[index - 1]["close"] if index else candle["close"]
        true_ranges.append(max(
            candle["high"] - candle["low"],
            abs(candle["high"] - previous_close),
            abs(candle["low"] - previous_close),
        ))
        body = abs(candle["close"] - candle["open"])
        candle_range = max(candle["high"] - candle["low"], 1e-12)
        upper_wick = candle["high"] - max(candle["open"], candle["close"])
        lower_wick = min(candle["open"], candle["close"]) - candle["low"]
        candle["change_pct"] = round((candle["close"] / previous_close - 1.0) * 100.0, 5) if previous_close > 0 else 0.0
        candle["body_pct_of_range"] = round(body / candle_range * 100.0, 2)
        candle["upper_wick_pct_of_range"] = round(max(upper_wick, 0.0) / candle_range * 100.0, 2)
        candle["lower_wick_pct_of_range"] = round(max(lower_wick, 0.0) / candle_range * 100.0, 2)
        candle["candle_bias"] = "BULLISH" if candle["close"] > candle["open"] else "BEARISH" if candle["close"] < candle["open"] else "DOJI"

    atr_values = true_ranges[-14:]
    atr = sum(atr_values) / len(atr_values) if atr_values else 0.0
    prior_candles = normalized[-21:-1]
    recent_resistance = max((x["high"] for x in prior_candles), default=last["close"])
    recent_support = min((x["low"] for x in prior_candles), default=last["close"])
    latest_quote_volume = last["quote_volume_usdt"]
    prior_volumes = [x["quote_volume_usdt"] for x in normalized[-11:-1] if x["quote_volume_usdt"] > 0]
    average_prior_volume = sum(prior_volumes) / len(prior_volumes) if prior_volumes else 0.0
    volume_ratio = latest_quote_volume / average_prior_volume if average_prior_volume > 0 else 0.0
    breakout_confirmed = recent_resistance > 0 and last["close"] > recent_resistance * 1.001 and average_prior_volume > 0 and latest_quote_volume >= average_prior_volume * 1.2
    return {
        "interval": interval, "direction": direction, "change_pct": round(change_pct, 4),
        "atr": atr, "last_close": last["close"], "recent_support": recent_support,
        "recent_resistance": recent_resistance, "volume_ratio": round(volume_ratio, 3),
        "breakout_confirmed": breakout_confirmed,
        "candle_analysis": [dict(x) for x in normalized[-12:]],
        "closed_candles_analyzed": len(normalized),
    }


def add_spot_trade_plan(signal, atr, recent_resistance=0.0):
    """Attach volatility-scaled levels to a confirmed bullish spot setup."""
    price = float(signal["price"])
    if price <= 0:
        raise ValueError("Signal price must be positive")

    # Avoid stops that are unrealistically tight when ATR is very small.
    risk_distance = max(float(atr or 0.0) * 1.5, price * 0.005)
    signal["entry_price"] = round(price, 8)
    signal["stop_loss"] = round(max(price - risk_distance, price * 0.5), 8)
    signal["take_profit_1"] = round(price + risk_distance * 1.5, 8)
    signal["take_profit_2"] = round(price + risk_distance * 2.0, 8)
    resistance_distance_pct = (float(recent_resistance) / price - 1.0) * 100.0 if recent_resistance else 0.0
    signal["recent_resistance"] = round(float(recent_resistance or 0.0), 8)
    signal["resistance_distance_pct"] = round(resistance_distance_pct, 3)
    signal["risk_reward_tp1"] = "1:1.5"
    signal["risk_reward_tp2"] = "1:2"
    signal["action_hint"] = "SPOT_BUY_SETUP"


def calculate_quality_score(signal, timeframe_analysis):
    """Rank short-hold setups by liquidity, aligned timeframes and room to resistance."""
    volume = max(float(signal.get("volume_usdt", 0.0)), 1.0)
    volume_score = min((volume / 1_000_000.0) ** 0.25, 3.0) * 5.0
    momentum = float(signal.get("change_24h", 0.0))
    momentum_score = max(0.0, 12.0 - abs(momentum - 7.0)) * 0.65
    bullish_count = sum(1 for item in timeframe_analysis.values() if item.get("direction") == "BULLISH")
    bullish_score = bullish_count * 3.0
    short_score = sum(max(-2.0, min(2.0, float(timeframe_analysis[tf].get("change_pct", 0.0)))) for tf in ("15m", "30m", "1h")) * 1.2
    distance = float(signal.get("resistance_distance_pct", 0.0))
    resistance_penalty = max(0.0, 1.25 - distance) * 8.0 if 0.0 < distance < 1.25 else 0.0
    return round(volume_score + momentum_score + bullish_score + short_score - resistance_penalty, 2)


def confirm_spot_signals(candidates):
    confirmed = []
    for signal in candidates:
        try:
            # Fast charts first: reject obvious late entries before requesting all eight intervals.
            trend_15m = get_trend(signal["symbol"], "15m")
            trend_1h = get_trend(signal["symbol"], "1h")
            signal["trend_15m_pct"] = trend_15m["change_pct"]
            signal["trend_1h_pct"] = trend_1h["change_pct"]
            if signal["direction"] == "BULLISH":
                change_24h = float(signal.get("change_24h", 0.0))
                short_change = float(trend_15m.get("change_pct", 0.0))
                hourly_change = float(trend_1h.get("change_pct", 0.0))
                resistance = float(trend_15m.get("recent_resistance", 0.0))
                price = float(signal.get("price", 0.0))
                resistance_distance = ((resistance / price) - 1.0) * 100.0 if resistance > 0 and price > 0 else 0.0
                if change_24h > MAX_BULLISH_CHANGE_24H or short_change > MAX_15M_CHANGE or hourly_change > MAX_1H_CHANGE:
                    signal["status"] = "CANDIDATE_NOT_CONFIRMED"
                    signal["confirmation_status"] = "OVEREXTENDED_MOVE"
                    continue
                if 0.0 < resistance_distance < 0.75:
                    signal["status"] = "CANDIDATE_NOT_CONFIRMED"
                    signal["confirmation_status"] = "RESISTANCE_TOO_CLOSE"
                    continue
                if resistance > 0 and price > 0:
                    risk_distance = max(float(trend_15m.get("atr", 0.0) or 0.0) * 1.5, price * 0.005)
                    tp1_distance_pct = (risk_distance * 1.5 / price) * 100.0
                    if resistance_distance > 0 and resistance_distance <= tp1_distance_pct * 1.15:
                        signal["status"] = "CANDIDATE_NOT_CONFIRMED"
                        signal["confirmation_status"] = "INSUFFICIENT_RESISTANCE_ROOM"
                        continue
                    if resistance_distance <= 0 and not trend_15m.get("breakout_confirmed", False):
                        signal["status"] = "CANDIDATE_NOT_CONFIRMED"
                        signal["confirmation_status"] = "BREAKOUT_NOT_CONFIRMED"
                        continue
            if trend_15m["direction"] != signal["direction"] or trend_1h["direction"] != signal["direction"]:
                signal["status"] = "CANDIDATE_NOT_CONFIRMED"
                signal["confirmation_status"] = "NOT_CONFIRMED_15M_1H"
                continue

            timeframe_analysis = {"15m": trend_15m, "1h": trend_1h}
            remaining_intervals = [interval for interval in TIMEFRAMES if interval not in timeframe_analysis]
            # Fetch the six remaining intervals concurrently to keep the five-minute scan practical.
            with ThreadPoolExecutor(max_workers=6) as executor:
                futures = {
                    interval: executor.submit(get_trend, signal["symbol"], interval)
                    for interval in remaining_intervals
                }
                for interval, future in futures.items():
                    timeframe_analysis[interval] = future.result()
            ordered = {tf: timeframe_analysis[tf] for tf in TIMEFRAMES}
            directions = {tf: item.get("direction", "NEUTRAL") for tf, item in ordered.items()}
            bullish_count = sum(direction == "BULLISH" for direction in directions.values())
            signal["timeframes_checked"] = len(TIMEFRAMES)
            signal["bullish_timeframes"] = bullish_count
            signal["timeframe_summary"] = {
                tf: {
                    "direction": ordered[tf].get("direction"),
                    "change_pct": ordered[tf].get("change_pct"),
                    "atr": round(float(ordered[tf].get("atr", 0.0) or 0.0), 10),
                    "recent_support": ordered[tf].get("recent_support"),
                    "recent_resistance": ordered[tf].get("recent_resistance"),
                    "volume_ratio": ordered[tf].get("volume_ratio"),
                    "breakout_confirmed": ordered[tf].get("breakout_confirmed", False),
                    "closed_candles_analyzed": ordered[tf].get("closed_candles_analyzed"),
                    "candle_analysis": ordered[tf].get("candle_analysis", []),
                } for tf in TIMEFRAMES
            }

            if signal["direction"] == "BULLISH":
                required_short = all(directions[tf] == "BULLISH" for tf in ("15m", "30m", "1h"))
                higher = ("4h", "8h", "12h", "1d")
                higher_not_bearish = sum(directions[tf] != "BEARISH" for tf in higher)
                strong_higher_bearish = any(directions[tf] == "BEARISH" and float(ordered[tf].get("change_pct", 0.0)) <= -3.0 for tf in higher)
                if not required_short or bullish_count < MIN_BULLISH_TIMEFRAMES or higher_not_bearish < 2 or strong_higher_bearish:
                    signal["status"] = "CANDIDATE_NOT_CONFIRMED"
                    signal["confirmation_status"] = "NOT_CONFIRMED_8_TIMEFRAMES"
                    continue
                add_spot_trade_plan(signal, trend_15m.get("atr", 0.0), trend_15m.get("recent_resistance", 0.0))
                signal["quality_score"] = calculate_quality_score(signal, ordered)
                signal["action_hint"] = "SPOT_BUY_SETUP_MAX_24H_HOLD"
            else:
                bearish_count = sum(direction == "BEARISH" for direction in directions.values())
                if bearish_count < MIN_BULLISH_TIMEFRAMES:
                    signal["status"] = "CANDIDATE_NOT_CONFIRMED"
                    signal["confirmation_status"] = "NOT_CONFIRMED_8_TIMEFRAMES"
                    continue
                signal["action_hint"] = "SPOT_SELL_OR_AVOID_BUY; SHORT_REQUIRES_FUTURES"

            # Keep legacy status names so the existing Android app remains compatible.
            signal["status"] = "CONFIRMED_15M_1H"
            signal["confirmation_status"] = "CONFIRMED_8_TIMEFRAMES"
            signal["max_holding_hours"] = 24
            signal["selected_top_signal"] = False
            confirmed.append(signal)
        except Exception as error:
            signal["status"] = "CANDIDATE_NOT_CONFIRMED"
            signal["confirmation_status"] = "DATA_UNAVAILABLE"
            signal["confirmation_error"] = str(error)[:160]

    bullish = [item for item in confirmed if item.get("direction") == "BULLISH"]
    bullish.sort(key=lambda item: float(item.get("quality_score", 0.0)), reverse=True)
    selected = bullish[:MAX_CONFIRMED_SPOT_SIGNALS]
    for rank, signal in enumerate(selected, start=1):
        signal["rank"] = rank
        signal["selected_top_signal"] = True
    for signal in bullish[MAX_CONFIRMED_SPOT_SIGNALS:]:
        signal["status"] = "CONFIRMED_NOT_TOP_2"
        signal["confirmation_status"] = "CONFIRMED_NOT_TOP_2"
        signal["selected_top_signal"] = False
    # Keep the verbose candle-by-candle payload only for actionable top picks.
    # Other candidates retain timeframe-level summaries to keep signals.json compact.
    for signal in candidates:
        if signal.get("selected_top_signal") is not True:
            for details in signal.get("timeframe_summary", {}).values():
                details.pop("candle_analysis", None)
    return candidates, confirmed


def empty_report(now, status, error=None):
    return {
        "scan_time_utc": now.isoformat(),
        "scan_time_local": now.astimezone(LOCAL_TZ).isoformat(),
        "timezone": "Asia/Kabul",
        "scanner_status": status,
        "valid_minutes": VALID_MINUTES,
        "signals_found": 0,
        "confirmed_signals_found": 0,
        "spot_confirmed_signals": [],
        "spot_signals": [],
        "spot_top10_signals": [],
        "error": error,
        "notice": (
            "No fresh spot signals are available. Do not use older signal files "
            "or this report as trade entries."
        ),
    }


def scan_market():
    now = datetime.now(timezone.utc)
    print("Starting market scan:", now.isoformat())

    try:
        spot_data = get_data(SPOT_API)
        if not isinstance(spot_data, list):
            raise RuntimeError("Spot API returned an unexpected response")
        spot_candidates = build_signals(spot_data, "SPOT", now)
        spot_candidates, all_confirmed = confirm_spot_signals(spot_candidates)
        top10 = sorted(
            [
                item for item in all_confirmed
                if item.get("direction") == "BULLISH"
                and item.get("status") in ("CONFIRMED_15M_1H", "CONFIRMED_NOT_TOP_2")
            ],
            key=lambda item: float(item.get("quality_score", 0.0)),
            reverse=True,
        )[:MAX_TOP_10_SIGNALS]
        for rank, item in enumerate(top10, start=1):
            item["top10_rank"] = rank
        spot_confirmed = sorted(
            [
                item for item in all_confirmed
                if item.get("direction") == "BULLISH"
                and item.get("selected_top_signal") is True
                and item.get("status") == "CONFIRMED_15M_1H"
            ],
            key=lambda item: float(item.get("quality_score", 0.0)),
            reverse=True,
        )[:MAX_CONFIRMED_SPOT_SIGNALS]
    except Exception as error:
        # Replace any old file with an explicit empty error report, never stale signals.
        report = empty_report(
            now,
            "ERROR",
            f"{SPOT_API}: {str(error).replace(chr(10), ' ')}",
        )
        report["notice"] = (
            "Spot data could not be fetched. All signal lists are empty to avoid "
            "showing stale signals. Wait for the next successful scan."
        )
        with open("signals.json", "w", encoding="utf-8") as file:
            json.dump(report, file, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    report = {
        "scan_time_utc": now.isoformat(),
        "scan_time_local": now.astimezone(LOCAL_TZ).isoformat(),
        "timezone": "Asia/Kabul",
        "scanner_status": "SUCCESS",
        "valid_minutes": VALID_MINUTES,
        "signals_found": len(spot_confirmed),
        "confirmed_signals_found": len(spot_confirmed),
        "spot_confirmed_signals": spot_confirmed,
        "spot_top10_signals": top10,
        # Backward-compatible app field intentionally contains ONLY actionable
        # confirmed signals. Unconfirmed candidates are diagnostics, never entries.
        "spot_signals": spot_confirmed,
        "spot_candidates": spot_candidates,
        "notice": (
            "Binance spot scanner analyzes closed candles across 15m, 30m, 1h, 2h, 4h, 8h, 12h and 1d. "
            "The ten highest-scoring confirmed bullish setups are exposed in spot_top10_signals; "
            "the top two are published as actionable signals for Android compatibility. "
            "Bullish setups require aligned 15m/30m/1h direction, at least five bullish timeframes, "
            "higher-timeframe risk checks and sufficient resistance room. Each signal includes "
            "candle-by-candle diagnostics for the latest 12 closed candles per timeframe. "
            "Signals expire after 15 minutes and the intended maximum holding period is 24 hours. "
            "Scores and levels do not guarantee profit."
        ),
    }

    with open("signals.json", "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("Market scan completed.")


if __name__ == "__main__":
    try:
        scan_market()
    except Exception as error:
        print("Scanner error:", repr(error))
        raise
