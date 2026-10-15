import json
import urllib.request
from datetime import datetime, timezone

API_URL = "https://api.binance.com/api/v3/ticker/24hr"


def get_market_data():
    request = urllib.request.Request(
        API_URL,
        headers={"User-Agent": "CryptoSignalScanner/1.0"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def scan_market():
    data = get_market_data()
    results = []

    for coin in data:
        symbol = coin.get("symbol", "")

        if not symbol.endswith("USDT"):
            continue

        try:
            price = float(coin["lastPrice"])
            change = float(coin["priceChangePercent"])
            volume = float(coin["quoteVolume"])

            if price <= 0 or volume < 1_000_000:
                continue

            if change >= 5:
                direction = "BULLISH"
            elif change <= -5:
                direction = "BEARISH"
            else:
                continue

            results.append({
                "symbol": symbol,
                "price": price,
                "change_24h": change,
                "volume_usdt": volume,
                "direction": direction
            })

        except (ValueError, KeyError):
            continue

    results.sort(
        key=lambda item: abs(item["change_24h"]),
        reverse=True
    )

    report = {
        "scan_time_utc": datetime.now(timezone.utc).isoformat(),
        "signals_found": len(results),
        "signals": results[:20]
    }

    with open("signals.json", "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        scan_market()
    except Exception as error:
        print(f"Scanner error: {error}")
        raise
