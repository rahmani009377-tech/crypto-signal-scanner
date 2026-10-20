
import json
import urllib.request
from datetime import datetime, timezone, timedelta

SPOT_API = "https://data-api.binance.vision/api/v3/ticker/24hr"
FUTURES_APIS = [
    "https://fapi.binance.com/fapi/v1/ticker/24hr",
    "https://fapi1.binance.com/fapi/v1/ticker/24hr",
]
MIN_VOLUME = 1_000_000
MIN_CHANGE = 5.0
VALID_MINUTES = 15


def get_data(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "CryptoSignalScanner/1.0"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def get_futures_data():
    for url in FUTURES_APIS:
        try:
            return get_data(url)
        except Exception as error:
            print(f"Futures endpoint unavailable: {error}")
    return []


def build_signals(data, market_type, now, errors):
    results = []

    for coin in data:
        symbol = coin.get("symbol", "")

        if not symbol.endswith("USDT"):
            continue

        try:
            price = float(coin["lastPrice"])
            change = float(coin["priceChangePercent"])
            volume = float(coin["quoteVolume"])

            if price <= 0 or volume < MIN_VOLUME:
                continue

            if change >= MIN_CHANGE:
                direction = "BULLISH"
            elif change <= -MIN_CHANGE:
                direction = "BEARISH"
            else:
                continue

            # These are market-momentum candidates, not confirmed entries.
            results.append({
                "symbol": symbol,
                "market_type": market_type,
                "price": price,
                "change_24h": change,
                "volume_usdt": volume,
                "direction": direction,
                "created_at": now.isoformat(),
                "expires_at": (
                    now + timedelta(minutes=VALID_MINUTES)
                ).isoformat(),
                "status": "CANDIDATE_NOT_CONFIRMED"
            })

        except (ValueError, KeyError, TypeError):
            continue

    results.sort(
        key=lambda item: abs(item["change_24h"]),
        reverse=True
    )
    return results


def scan_market():
    now = datetime.now(timezone.utc)
    errors = []

    try:
        spot_data = get_data(SPOT_API)
    except Exception as error:
        raise RuntimeError(f"Spot market unavailable: {error}")

    spot_signals = build_signals(
        spot_data, "SPOT", now, errors
    )

    futures_data = get_futures_data()
    futures_signals = build_signals(
        futures_data, "FUTURES", now, errors
    )

    # Keep only the latest scan; do not build a backlog of old signals.
    report = {
        "scan_time_utc": now.isoformat(),
        "valid_minutes": VALID_MINUTES,
        "signals_found": len(spot_signals) + len(futures_signals),
        "spot_signals": spot_signals[:20],
        "futures_signals": futures_signals[:20],
        "notice": (
            "Candidates use 24-hour price change only. "
            "They are not confirmed entries. Recheck live price "
            "and expiry before considering any trade."
        )
    }

    with open("signals.json", "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    scan_market()
