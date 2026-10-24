# Binance Crypto Signal Scanner

A free, read-only scanner for Binance spot markets. It never places trades and does not need Binance API keys.

## Short-term spot scanner
- GitHub Actions requests a scan every five minutes; GitHub may delay scheduled jobs, so this is not a guaranteed real-time cadence.
- Scans liquid USDT spot pairs and filters candidates to avoid chasing extreme 24-hour pumps.
- Analyzes closed candles in **15m, 30m, 1h, 2h, 4h, 8h, 12h and 1d** intervals.
- For each interval, analyzes OHLC, quote volume, candle body/wicks, candle direction, ATR, support/resistance and relative volume. The report includes the latest 12 closed candles per timeframe for each analyzed candidate.
- A bullish setup requires 15m, 30m and 1h alignment, at least five bullish timeframes, checks against strong higher-timeframe weakness, and enough room to nearby resistance.
- The ten best confirmed bullish candidates are listed in `spot_top10_signals`; the top two are placed in `spot_signals` and `spot_confirmed_signals` to preserve Android compatibility. Signals expire after 15 minutes and show an intended maximum holding period of 24 hours.
- Stop loss and take-profit levels are estimates, not guaranteed execution prices. No strategy can guarantee profit or prevent all losses.

## New Binance listing watcher
- `listing_watcher.py` checks Binance's official new-cryptocurrency-listing announcement category (catalog 48) and tries to parse an explicit trading start time from the announcement.
- When a start time is parsed, it schedules Telegram alerts for **24 hours, 12 hours and 2 hours before start**, plus a start-time market check. All times are reported in **Asia/Kabul**.
- Alert delivery is attempted only when the `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` GitHub Actions secrets are configured. If they are missing, the listing report still records upcoming listings, but no phone push is delivered.
- Alerts are deduplicated after successful Telegram delivery. If the listing time changes, scheduled alert status is reset.
- Announcements without a reliably parsed trading time are reported as `TIME_NOT_PARSED` and are not given invented alert times. The watcher never buys automatically.

## Reports
- `signals.json`: current short-term spot signals.
- `listing_report.json`: upcoming listings, parsed Kabul start times, due alerts and feed warnings.
- `listing_state.json`: listing alert deduplication state. Keep this file committed so alerts are not repeatedly sent on each run.

## How to run
1. Open [GitHub Actions](https://github.com/rahmani009377-tech/crypto-signal-scanner/actions).
2. Select **Binance Signal Scanner** and choose **Run workflow** for an immediate scan.
3. Open [signals.json](https://github.com/rahmani009377-tech/crypto-signal-scanner/blob/main/signals.json) for spot signals or [listing_report.json](https://github.com/rahmani009377-tech/crypto-signal-scanner/blob/main/listing_report.json) for listing notices.

Use only signals whose `expires_at` is still in the future. `CANDIDATE_NOT_CONFIRMED` is not a confirmed setup. Check the live Binance price, spread, order-book liquidity and trading status before entering any trade.
