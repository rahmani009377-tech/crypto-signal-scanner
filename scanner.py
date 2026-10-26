import json
import re
import urllib.request
import urllib.error
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
    # Request enough candles to estimate volatility, and ignore the still-open candle.
    url = (
        f"{SPOT_KLINES_API}?symbol={symbol}"
        f"&interval={interval}&limit=16"
    )
    candles = get_data(url)
    if not isinstance(candles, list) or len(candles) < 6:
        raise RuntimeError(f"Not enough {interval} candles for {symbol}")

    closed = candles[:-1]
    old_close = float(closed[-4][4])
    previous_close = float(closed[-2][4])
    last_close = float(closed[-1][4])
    if old_close <= 0 or previous_close <= 0 or last_close <= 0:
        raise RuntimeError(f"Invalid {interval} candle price for {symbol}")

    change_pct = (last_close / old_close - 1.0) * 100.0
    if last_close > previous_close and change_pct > 0:
        direction = "BULLISH"
    elif last_close < previous_close and change_pct < 0:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    true_ranges = []
    for index in range(1, len(closed)):
        high = float(closed[index][2])
        low = float(closed[index][3])
        previous = float(closed[index - 1][4])
        if high <= 0 or low <= 0 or high < low:
            raise RuntimeError(f"Invalid {interval} candle range for {symbol}")
        true_ranges.append(max(high - low, abs(high - previous), abs(low - previous)))

    atr = sum(true_ranges[-14:]) / len(true_ranges[-14:]) if true_ranges else 0.0

    # Use the 12 candles BEFORE the latest closed candle as resistance; including
    # the latest candle's high can hide a breakout or distort room-to-target.
    prior_candles = closed[-13:-1] if len(closed) > 1 else closed[:-1]
    recent_highs = [float(candle[2]) for candle in prior_candles]
    recent_resistance = max(recent_highs) if recent_highs else last_close

    # Require a candle-close breakout with stronger quote volume when price is
    # already above resistance. A live ticker tick alone is not a breakout.
    latest_quote_volume = float(closed[-1][7]) if len(closed[-1]) > 7 else 0.0
    prior_volumes = [
        float(candle[7]) for candle in closed[-11:-1]
        if len(candle) > 7 and float(candle[7]) > 0
    ]
    average_prior_volume = (
        sum(prior_volumes) / len(prior_volumes) if prior_volumes else 0.0
    )
    breakout_confirmed = (
        recent_resistance > 0
        and last_close > recent_resistance * 1.001
        and average_prior_volume > 0
        and latest_quote_volume >= average_prior_volume * 1.2
    )
    return {
        "direction": direction,
        "change_pct": round(change_pct, 4),
        "atr": atr,
        "last_close": last_close,
        "recent_resistance": recent_resistance,
        "breakout_confirmed": breakout_confirmed,
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


def calculate_quality_score(signal, trend_15m, trend_1h):
    """Rank confirmed bullish setups using trend, liquidity, momentum and resistance room."""
    volume = max(float(signal.get("volume_usdt", 0.0)), 1.0)
    volume_score = min(max((volume / 1_000_000.0) ** 0.25, 0.0), 3.0) * 5.0
    momentum_score = min(max(float(signal.get("change_24h", 0.0)), 0.0), 15.0) * 0.8
    short_trend_score = min(max(float(trend_15m.get("change_pct", 0.0)), 0.0), 3.0) * 4.0
    hourly_trend_score = min(max(float(trend_1h.get("change_pct", 0.0)), 0.0), 8.0) * 1.5
    distance = float(signal.get("resistance_distance_pct", 0.0))
    # Penalize entries immediately beneath recent resistance; a breakout above it is not penalized.
    resistance_penalty = max(0.0, 1.0 - distance) * 8.0 if 0.0 < distance < 1.0 else 0.0
    return round(volume_score + momentum_score + short_trend_score + hourly_trend_score - resistance_penalty, 2)


def confirm_spot_signals(candidates):
    confirmed = []
    for signal in candidates:
        # Check every candidate in the bounded scan list, rather than stopping after eight.
        try:
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
                # Reject late entries after a sharp move on the 15m/1h chart.
                if (
                    change_24h > MAX_BULLISH_CHANGE_24H
                    or short_change > MAX_15M_CHANGE
                    or hourly_change > MAX_1H_CHANGE
                ):
                    signal["status"] = "CANDIDATE_NOT_CONFIRMED"
                    signal["confirmation_status"] = "OVEREXTENDED_MOVE"
                    continue

                # A nearby ceiling can stop price before TP1. First reject a
                # very close ceiling, then require room for TP1 plus a buffer.
                if 0.0 < resistance_distance < 0.75:
                    signal["status"] = "CANDIDATE_NOT_CONFIRMED"
                    signal["confirmation_status"] = "RESISTANCE_TOO_CLOSE"
                    continue

                if resistance > 0 and price > 0:
                    risk_distance = max(
                        float(trend_15m.get("atr", 0.0) or 0.0) * 1.5,
                        price * 0.005,
                    )
                    tp1_distance_pct = (risk_distance * 1.5 / price) * 100.0
                    if resistance_distance > 0 and resistance_distance <= tp1_distance_pct * 1.15:
                        signal["status"] = "CANDIDATE_NOT_CONFIRMED"
                        signal["confirmation_status"] = "INSUFFICIENT_RESISTANCE_ROOM"
                        continue

                    # If price is already above the prior resistance, do not
                    # treat a live-price spike as a breakout without candle-close
                    # and relative-volume confirmation.
                    if resistance_distance <= 0 and not trend_15m.get("breakout_confirmed", False):
                        signal["status"] = "CANDIDATE_NOT_CONFIRMED"
                        signal["confirmation_status"] = "BREAKOUT_NOT_CONFIRMED"
                        continue
            if (
                trend_15m["direction"] == signal["direction"]
                and trend_1h["direction"] == signal["direction"]
            ):
                if signal["direction"] == "BULLISH":
                    add_spot_trade_plan(
                        signal,
                        trend_15m.get("atr", 0.0),
                        trend_15m.get("recent_resistance", 0.0),
                    )
                    signal["quality_score"] = calculate_quality_score(signal, trend_15m, trend_1h)
                else:
                    signal["action_hint"] = "SPOT_SELL_OR_AVOID_BUY; SHORT_REQUIRES_FUTURES"
                signal["status"] = "CONFIRMED_15M_1H"
                signal["confirmation_status"] = "CONFIRMED_15M_1H"
                confirmed.append(signal)
            else:
                signal["status"] = "CANDIDATE_NOT_CONFIRMED"
                signal["confirmation_status"] = "NOT_CONFIRMED_15M_1H"
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
    return candidates, confirmed


def summarize_candidates(candidates):
    """Expose why candidates were rejected so zero-signal scans are diagnosable."""
    reasons = {}
    for item in candidates:
        reason = item.get("confirmation_status", "NOT_CHECKED")
        reasons[reason] = reasons.get(reason, 0) + 1
    return {
        "candidates_checked": len(candidates),
        "bullish_candidates": sum(1 for item in candidates if item.get("direction") == "BULLISH"),
        "bearish_candidates": sum(1 for item in candidates if item.get("direction") == "BEARISH"),
        "confirmed_candidates": sum(
            1 for item in candidates if item.get("status") == "CONFIRMED_15M_1H"
        ),
        "rejection_reasons": dict(sorted(reasons.items(), key=lambda pair: (-pair[1], pair[0]))),
    }


def empty_report(now, status, error=None):
    return {
        "scan_time_utc": now.isoformat(),
        "scan_time_local": now.astimezone(LOCAL_TZ).isoformat(),
        "timezone": "Asia/Kabul",
        "scanner_status": status,
        "valid_minutes": VALID_MINUTES,
        "signals_found": 0,
        "confirmed_signals_found": 0,
        "scan_stats": summarize_candidates([]),
        "spot_confirmed_signals": [],
        "spot_signals": [],
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
        "scan_stats": summarize_candidates(spot_candidates),
        "spot_confirmed_signals": spot_confirmed,
        # Backward-compatible app field intentionally contains ONLY actionable
        # confirmed signals. Unconfirmed candidates are diagnostics, never entries.
        "spot_signals": spot_confirmed,
        "spot_candidates": spot_candidates,
        "notice": (
            "Conservative Binance spot scanner. Only the top two fully confirmed "
            "bullish setups are published in spot_signals and spot_confirmed_signals. "
            "Entries are rejected when resistance is too close, there is not enough "
            "room to TP1, or a breakout lacks candle-close/volume confirmation. "
            "Signals expire after 15 minutes. Scores and levels do not guarantee profit."
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
