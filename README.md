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
