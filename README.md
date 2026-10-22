# Binance Crypto Signal Scanner

A free, read-only scanner for Binance spot markets only. It never places trades and does not need Binance API keys.

## What it does
- GitHub Actions requests a scan every five minutes and also supports manual runs. GitHub may delay scheduled jobs, so five minutes is the requested cadence, not a guaranteed delivery interval.
- Reads public Binance spot market data and filters USDT pairs with a 24-hour move of at least 5% and quote volume of at least 1,000,000 USDT.
- Checks the top candidates against closed 15-minute and 1-hour candles. Only matching candidates are placed in `spot_confirmed_signals`.
- Confirmed bullish setups include an indicative entry price, ATR-based stop-loss, and two profit targets (risk/reward 1:1.5 and 1:2). These are estimates from the scan snapshot, not guaranteed execution prices.
- Confirmed bearish signals are labeled as sell/avoid-buy context for spot; they are not instructions to open a short position.
- Writes a fresh `signals.json` report with a Kabul timestamp and 15-minute expiry. If spot data fails, it replaces the report with an explicit error and empty signal lists rather than presenting stale signals.
- Runs unit tests and validates the generated report on each workflow run.

## How to use
1. Open the [Actions page](https://github.com/rahmani009377-tech/crypto-signal-scanner/actions).
2. Select **Binance Signal Scanner**.
3. Select **Run workflow** to request an immediate scan.
4. Open the [latest signals report](https://github.com/rahmani009377-tech/crypto-signal-scanner/blob/main/signals.json).

Use only signals whose `expires_at` is still in the future. `CANDIDATE_NOT_CONFIRMED` is not a confirmed setup. Check the current Binance price before acting; a scan price may already have moved.

## Notifications
Optional Telegram alert delivery is built in for **new confirmed bullish spot signals only** and deduplicates signals that are still active. It safely skips delivery until both secrets are configured: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Add them under **Repository → Settings → Secrets and variables → Actions → New repository secret**. Create the bot with Telegram's `@BotFather`, then obtain your chat ID. No token or chat ID was supplied, so alerts cannot be delivered yet. GitHub's scheduled runs may also start later than the requested five-minute cadence.

## Tests
The workflow runs:

```bash
python -m unittest discover -s tests -v
```

## Safety and limitations
- This is market screening, not financial advice or a profit guarantee.
- No automatic orders, API keys, withdrawals, or live trading.
- Stop-loss and target levels are volatility-based estimates. Gaps, slippage, fees, spread, and rapid moves can change realized results.
- A large 24-hour move may already be exhausted. Confirm liquidity, current price, and expiry before considering a trade.


## Android app

The Android project is in the repository root `app/`. The Android app's on-device notifications are independent of Telegram; no bot or Telegram token is required. It provides a Persian dashboard, manual spot scan, on-device market filtering, confirmed bullish setup cards, entry/stop-loss/take-profit estimates, an in-app background-scan toggle, local-notification toggle, and adjustable 24-hour volume/change filters.

### Build and install
1. Open the repository's **Actions** page and select **Build Android APK**.
2. Wait for the build to finish successfully.
3. Open the completed run, scroll to **Artifacts**, and download `rahmani-crypto-scanner-debug-apk`.
4. Extract the ZIP and install `app-debug.apk` on the Android phone.

Android background scheduling is managed by WorkManager. Android may delay background work, and periodic background scans have a minimum interval of 15 minutes; exact five-minute background scans cannot be guaranteed by Android. The app reads public Binance market data and does not place orders or require Binance credentials. Signal levels are estimates, not guarantees.
