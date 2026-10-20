
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

SPOT_API = (
    "https://data-api.binance.vision/api/v3/ticker/24hr"
)

FUTURES_APIS = [
    "https://fapi.binance.com/fapi/v1/ticker/24hr"
]

MIN_VOLUME = 1_000_000
MIN_CHANGE = 5.0
VALID_MINUTES = 15

def get_data(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")

            if not body.strip():
                raise RuntimeError(
                    f"Empty response; HTTP status={response.status}"
                )

            try:
                return json.loads(body)
            except json.JSONDecodeError:
                raise RuntimeError(
                    f"Invalid JSON; HTTP status={response.status}; "
                    f"body={body[:200]!r}"
                )

    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP {error.code}; body={body[:200]!r}"
        )


def get_futures_data():
    errors = []

    for url in FUTURES_APIS:
        try:
            data = get_data(url)

            if isinstance(data, list):
                print("Futures data received successfully.")
                return data, None

            errors.append(url + ": unexpected response")

        except Exception as error:
            message = str(error).replace("\n", " ")
            errors.append(url + ": " + message)
            print("Futures endpoint unavailable:", message)

    return [], " | ".join(errors)


def build_signals(data, market_type, now):
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

    return results[:20]


def scan_market():
    now = datetime.now(timezone.utc)

    print("Starting market scan:", now.isoformat())

    spot_data = get_data(SPOT_API)

    if not isinstance(spot_data, list):
        raise RuntimeError("Spot API returned an unexpected response")

    spot_signals = build_signals(
        spot_data, "SPOT", now
    )

    futures_data, futures_error = get_futures_data()

    futures_signals = build_signals(
        futures_data, "FUTURES", now
    )

    report = {
        "scan_time_utc": now.isoformat(),
        "valid_minutes": VALID_MINUTES,
        "signals_found": (
            len(spot_signals) + len(futures_signals)
        ),
        "spot_signals": spot_signals,
        "futures_signals": futures_signals,
        "futures_error": futures_error,
        "notice": (
            "These are candidates based on 24-hour price change, "
            "not confirmed trade entries. Check live price, "
            "trend and expiry before trading."
        )
    }

    with open("signals.json", "w", encoding="utf-8") as file:
        json.dump(
            report,
            file,
            ensure_ascii=False,
            indent=2
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("Market scan completed.")


if __name__ == "__main__":
    try:
        scan_market()
    except Exception as error:
        print("Scanner error:", repr(error))
        raise
