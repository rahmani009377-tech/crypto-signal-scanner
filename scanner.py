import json
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

SPOT_API = "https://data-api.binance.vision/api/v3/ticker/24hr"
SPOT_KLINES_API = "https://data-api.binance.vision/api/v3/klines"
FUTURES_API = "https://fapi.binance.com/fapi/v1/ticker/24hr"

MIN_VOLUME_USDT = 1_000_000
MIN_CHANGE_24H = 5.0
VALID_MINUTES = 15
MAX_SIGNALS_PER_MARKET = 20


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

    results.sort(key=lambda item: abs(item["change_24h"]), reverse=True)
    return results[:MAX_SIGNALS_PER_MARKET]


def get_trend(symbol, interval):
    url = (
        f"{SPOT_KLINES_API}?symbol={symbol}"
        f"&interval={interval}&limit=6"
    )
    candles = get_data(url)
    if not isinstance(candles, list) or len(candles) < 6:
        raise RuntimeError(f"Not enough {interval} candles for {symbol}")

    # Drop the last candle because it may still be forming.
    closed = candles[:-1]
    old_close = float(closed[-4][4])
    previous_close = float(closed[-2][4])
    last_close = float(closed[-1][4])
    if old_close <= 0:
        raise RuntimeError(f"Invalid {interval} candle price for {symbol}")

    change_pct = (last_close / old_close - 1.0) * 100.0
    if last_close > previous_close and change_pct > 0:
        direction = "BULLISH"
    elif last_close < previous_close and change_pct < 0:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    return {"direction": direction, "change_pct": round(change_pct, 4)}


def confirm_spot_signals(candidates):
    confirmed = []
    for index, signal in enumerate(candidates):
        if index >= 8:
            signal["status"] = "NOT_CHECKED_LIMIT"
            continue
        try:
            trend_15m = get_trend(signal["symbol"], "15m")
            trend_1h = get_trend(signal["symbol"], "1h")
            signal["trend_15m_pct"] = trend_15m["change_pct"]
            signal["trend_1h_pct"] = trend_1h["change_pct"]
            if (
                trend_15m["direction"] == signal["direction"]
                and trend_1h["direction"] == signal["direction"]
            ):
                signal["status"] = "CONFIRMED_15M_1H"
                confirmed.append(signal)
            else:
                signal["status"] = "NOT_CONFIRMED_15M_1H"
        except Exception as error:
            signal["status"] = "NOT_CONFIRMED_DATA_UNAVAILABLE"
            signal["confirmation_error"] = str(error)[:160]
    return candidates, confirmed


def empty_report(now, status, error=None):
    return {
        "scan_time_utc": now.isoformat(),
        "scanner_status": status,
        "valid_minutes": VALID_MINUTES,
        "signals_found": 0,
        "spot_signals": [],
        "futures_signals": [],
        "futures_error": error,
        "notice": (
            "No fresh signals are available. Do not use older signal files "
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
        spot_signals, spot_confirmed = confirm_spot_signals(spot_candidates)
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

    futures_signals = []
    futures_error = None
    try:
        futures_data = get_data(FUTURES_API)
        if not isinstance(futures_data, list):
            raise RuntimeError("Futures API returned an unexpected response")
        futures_signals = build_signals(futures_data, "FUTURES", now)
        print("Futures data received successfully.")
    except Exception as error:
        futures_error = f"{FUTURES_API}: {str(error).replace(chr(10), ' ')}"
        print("Futures data unavailable:", futures_error)

    report = {
        "scan_time_utc": now.isoformat(),
        "scanner_status": "SUCCESS",
        "valid_minutes": VALID_MINUTES,
        "signals_found": len(spot_signals) + len(futures_signals),
        "confirmed_signals_found": len(spot_confirmed),
        "spot_confirmed_signals": spot_confirmed,
        "spot_signals": spot_signals,
        "futures_signals": futures_signals,
        "futures_error": futures_error,
        "notice": (
            "spot_signals are momentum candidates. Only spot_confirmed_signals "
            "passed both closed 15-minute and 1-hour trend checks. Futures data "
            "may be unavailable due to Binance regional restrictions. These are "
            "still not guaranteed entries. Never act after expires_at."
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
