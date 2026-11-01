import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

import scanner


def bullish_trends(**overrides):
    base = {
        interval: {
            "direction": "BULLISH",
            "change_pct": 0.5,
            "atr": 1.0,
            "last_close": 100.0,
            "recent_resistance": 0.0,
            "breakout_confirmed": False,
        }
        for interval in scanner.TIMEFRAMES
    }
    for interval, values in overrides.items():
        base[interval].update(values)
    return base


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

    def candidate(self, symbol="TESTUSDT", **extra):
        item = {
            "symbol": symbol, "direction": "BULLISH", "price": 100.0,
            "change_24h": 8.0, "volume_usdt": 5_000_000.0,
        }
        item.update(extra)
        return item

    def test_filters_non_usdt_non_ascii_low_volume_and_small_moves(self):
        rows = [
            {"symbol": "BTCUSDT", "lastPrice": "100", "priceChangePercent": "6", "quoteVolume": "3000000"},
            {"symbol": "ETHBTC", "lastPrice": "1", "priceChangePercent": "20", "quoteVolume": "9000000"},
            {"symbol": "牛来USDT", "lastPrice": "1", "priceChangePercent": "20", "quoteVolume": "9000000"},
            {"symbol": "LOWVOLUSDT", "lastPrice": "1", "priceChangePercent": "8", "quoteVolume": "999999"},
            {"symbol": "SMALLUSDT", "lastPrice": "1", "priceChangePercent": "2.9", "quoteVolume": "5000000"},
        ]
        result = scanner.build_signals(rows, "SPOT", self.now)
        self.assertEqual([item["symbol"] for item in result], ["BTCUSDT"])

    def test_excludes_extreme_bullish_pumps(self):
        rows = [
            {"symbol": "EXTREMEUSDT", "lastPrice": "1", "priceChangePercent": "45", "quoteVolume": "9000000"},
            {"symbol": "CLEANUSDT", "lastPrice": "1", "priceChangePercent": "12", "quoteVolume": "3000000"},
        ]
        self.assertEqual([x["symbol"] for x in scanner.build_signals(rows, "SPOT", self.now)], ["CLEANUSDT"])

    def test_candidate_expiry_is_15_minutes(self):
        rows = [{"symbol": "UPUSDT", "lastPrice": "2", "priceChangePercent": "5", "quoteVolume": "3000000"}]
        item = scanner.build_signals(rows, "SPOT", self.now)[0]
        self.assertEqual(datetime.fromisoformat(item["expires_at"]), self.now + timedelta(minutes=15))

    def test_multi_timeframe_fetch_checks_all_eight_intervals(self):
        with patch.object(scanner, "get_trend", return_value={"direction": "BULLISH"}) as mocked:
            result = scanner.get_multi_timeframe_trends("BTCUSDT")
        self.assertEqual(list(result), list(scanner.TIMEFRAMES))
        self.assertEqual(mocked.call_count, 8)
        self.assertEqual([call.args[1] for call in mocked.call_args_list], list(scanner.TIMEFRAMES))

    def test_bullish_signal_gets_levels_and_eight_timeframe_metadata(self):
        candidates = [self.candidate()]
        with patch.object(scanner, "get_multi_timeframe_trends", return_value=bullish_trends()):
            results, confirmed = scanner.confirm_spot_signals(candidates)
        self.assertEqual(len(confirmed), 1)
        signal = confirmed[0]
        self.assertEqual(signal["status"], "CONFIRMED_8TF")
        self.assertEqual(signal["timeframes_checked"], list(scanner.TIMEFRAMES))
        self.assertEqual(signal["bullish_timeframes"], 8)
        self.assertLess(signal["stop_loss"], signal["entry_price"])
        self.assertGreater(signal["take_profit_1"], signal["entry_price"])
        self.assertGreater(signal["take_profit_2"], signal["take_profit_1"])
        self.assertEqual(signal["risk_reward_tp1"], "1:1.5")
        self.assertEqual(signal["risk_reward_tp2"], "1:2")
        self.assertTrue(signal["selected_top_signal"])

    def test_requires_15m_30m_and_1h_bullish(self):
        trends = bullish_trends(**{"30m": {"direction": "NEUTRAL"}})
        candidates = [self.candidate()]
        with patch.object(scanner, "get_multi_timeframe_trends", return_value=trends):
            results, confirmed = scanner.confirm_spot_signals(candidates)
        self.assertEqual(confirmed, [])
        self.assertEqual(results[0]["confirmation_status"], "SHORT_TIMEFRAME_ALIGNMENT_FAILED")

    def test_requires_at_least_five_bullish_timeframes(self):
        trends = bullish_trends(**{
            "2h": {"direction": "BEARISH"},
            "4h": {"direction": "BEARISH"},
            "8h": {"direction": "BEARISH"},
            "12h": {"direction": "NEUTRAL"},
        })
        candidates = [self.candidate()]
        with patch.object(scanner, "get_multi_timeframe_trends", return_value=trends):
            results, confirmed = scanner.confirm_spot_signals(candidates)
        self.assertEqual(confirmed, [])
        self.assertEqual(results[0]["confirmation_status"], "MULTI_TIMEFRAME_ALIGNMENT_FAILED")

    def test_rejects_overextended_move(self):
        candidates = [self.candidate(change_24h=19.0)]
        with patch.object(scanner, "get_multi_timeframe_trends", return_value=bullish_trends()):
            results, confirmed = scanner.confirm_spot_signals(candidates)
        self.assertEqual(confirmed, [])
        self.assertEqual(results[0]["confirmation_status"], "OVEREXTENDED_MOVE")

    def test_rejects_resistance_too_close(self):
        trends = bullish_trends(**{"15m": {"recent_resistance": 100.3}})
        candidates = [self.candidate()]
        with patch.object(scanner, "get_multi_timeframe_trends", return_value=trends):
            results, confirmed = scanner.confirm_spot_signals(candidates)
        self.assertEqual(confirmed, [])
        self.assertEqual(results[0]["confirmation_status"], "RESISTANCE_TOO_CLOSE")

    def test_rejects_insufficient_room_before_first_target(self):
        trends = bullish_trends(**{"15m": {"recent_resistance": 101.5, "atr": 1.0}})
        candidates = [self.candidate()]
        with patch.object(scanner, "get_multi_timeframe_trends", return_value=trends):
            results, confirmed = scanner.confirm_spot_signals(candidates)
        self.assertEqual(confirmed, [])
        self.assertEqual(results[0]["confirmation_status"], "INSUFFICIENT_RESISTANCE_ROOM")

    def test_rejects_unconfirmed_breakout(self):
        trends = bullish_trends(**{"15m": {"recent_resistance": 99.0, "breakout_confirmed": False}})
        candidates = [self.candidate()]
        with patch.object(scanner, "get_multi_timeframe_trends", return_value=trends):
            results, confirmed = scanner.confirm_spot_signals(candidates)
        self.assertEqual(confirmed, [])
        self.assertEqual(results[0]["confirmation_status"], "BREAKOUT_NOT_CONFIRMED")

    def test_rejects_live_price_far_above_last_closed_candle(self):
        trends = bullish_trends(**{"15m": {"last_close": 98.0}})
        candidates = [self.candidate(price=100.0)]
        with patch.object(scanner, "get_multi_timeframe_trends", return_value=trends):
            results, confirmed = scanner.confirm_spot_signals(candidates)
        self.assertEqual(confirmed, [])
        self.assertEqual(results[0]["confirmation_status"], "LIVE_PRICE_TOO_FAR_ABOVE_CLOSED_CANDLE")

    def test_selects_only_top_three_of_ten_candidates(self):
        candidates = [self.candidate(f"COIN{i}USDT", volume_usdt=5_000_000 + i) for i in range(10)]
        with patch.object(scanner, "get_multi_timeframe_trends", return_value=bullish_trends()):
            results, confirmed = scanner.confirm_spot_signals(candidates)
        selected = [x for x in confirmed if x.get("selected_top_signal")]
        self.assertEqual(len(selected), 3)
        self.assertEqual(sum(x["status"] == "CONFIRMED_NOT_TOP_3" for x in results), 7)

    def test_only_top_ten_candidates_receive_deep_scan(self):
        candidates = [self.candidate(f"COIN{i}USDT", volume_usdt=10_000_000 - i) for i in range(12)]
        with patch.object(scanner, "get_multi_timeframe_trends", return_value=bullish_trends()) as mocked:
            results, confirmed = scanner.confirm_spot_signals(candidates)
        self.assertEqual(mocked.call_count, 10)
        self.assertEqual(sum(x.get("confirmation_status") == "NOT_IN_TOP_10" for x in results), 2)

    def test_data_error_does_not_create_signal(self):
        candidates = [self.candidate()]
        with patch.object(scanner, "get_multi_timeframe_trends", side_effect=RuntimeError("offline")):
            results, confirmed = scanner.confirm_spot_signals(candidates)
        self.assertEqual(confirmed, [])
        self.assertEqual(results[0]["confirmation_status"], "DATA_UNAVAILABLE")

    def test_trade_plan_rejects_nonpositive_price(self):
        with self.assertRaises(ValueError):
            scanner.add_spot_trade_plan({"price": 0}, 1.0)

    def test_empty_report_does_not_publish_stale_signals(self):
        report = scanner.empty_report(self.now, "ERROR", "test failure")
        self.assertEqual(report["spot_signals"], [])
        self.assertEqual(report["spot_confirmed_signals"], [])
        self.assertEqual(report["confirmed_signals_found"], 0)
        self.assertEqual(report["signals_found"], 0)
        self.assertEqual(report["scanner_status"], "ERROR")

    def test_stats_and_signal_state_distinguish_buy_from_bearish_context(self):
        candidates = [
            {"direction": "BULLISH", "status": "CANDIDATE_NOT_CONFIRMED",
             "confirmation_status": "INSUFFICIENT_RESISTANCE_ROOM", "deep_scan_attempted": True},
            {"direction": "BEARISH", "status": "CONFIRMED_BEARISH_CONTEXT",
             "confirmation_status": "CONFIRMED_8TF_BEARISH_CONTEXT", "deep_scan_attempted": True},
        ]
        stats = scanner.summarize_candidates(candidates)
        self.assertEqual(stats["candidates_total"], 2)
        self.assertEqual(stats["candidates_checked"], 2)
        self.assertEqual(stats["deep_scan_attempted"], 2)
        self.assertEqual(stats["not_deep_scanned"], 0)
        state = scanner.summarize_signal_state(candidates, [])
        self.assertEqual(state["actionable_spot_buy_count"], 0)
        self.assertEqual(state["confirmed_bearish_context_count"], 1)
        self.assertEqual(state["bullish_candidates_rejected"], 1)
        self.assertEqual(state["buy_signal_state"], "NO_CONFIRMED_SPOT_BUY_SETUP")


if __name__ == "__main__":
    unittest.main()
