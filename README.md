# Binance Crypto Signal Scanner

A read-only market scanner. It never places trades and never needs Binance API keys.

## What it does
- Runs from GitHub Actions on a five-minute schedule, and can also be started manually.
- Reads Binance public spot market data.
- Filters USDT pairs by 24-hour move (at least 5% up/down) and quote volume (at least 1,000,000 USDT).
- Checks closed 15-minute and 1-hour candles for the top candidates. Only candidates agreeing with both trends appear in `spot_confirmed_signals`.
- Writes the latest scan to `signals.json`, including timestamps and 15-minute expiry.
- If spot data fails, it writes an empty error report instead of leaving old signals looking current.
- Attempts the official Binance Futures public endpoint. Futures may be unavailable from GitHub-hosted runners due to HTTP 451 or other access restrictions; this is reported in `futures_error`.

## How to use
1. Open the repository's **Actions** tab.
2. Choose **Binance Signal Scanner**.
3. Select **Run workflow** to request a scan now.
4. Open `signals.json` on the `main` branch to view the latest output.

Scheduled runs are approximate; GitHub may delay cron jobs. The JSON file is not a phone notification service. Old results must not be used: check `scan_time_utc` and each signal's `expires_at`. A signal with status `CANDIDATE_NOT_CONFIRMED` is not a confirmed entry.

## Tests
Run locally with Python 3.12 or newer:

```bash
python -m unittest discover -s tests -v
```

## Safety and limitations
- This is market screening, not financial advice or a guarantee of profit.
- No automatic buying/selling, no API secrets, and no withdrawals.
- A 24-hour price change can reflect a move that is already over. Confirm current price, liquidity, trend, and expiry before making any decision.
- Spot trend confirmation does not automatically mean the trade is safe.
- Futures data availability is not guaranteed in restricted regions.
