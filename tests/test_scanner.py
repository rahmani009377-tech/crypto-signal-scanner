import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

import scanner


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

    def test_filters_non_usdt_and_non_ascii_symbols(self):
        rows = [
            {"symbol": "BTCUSDT", "lastPrice": "100", "priceChangePercent": "6", "quoteVolume": "3000000"},
            {"symbol": "ETHBTC", "lastPrice": "1", "priceChangePercent": "20", "quoteVolume": "2000000"},
            {"symbol": "牛来USDT", "lastPrice": "1", "priceChangePercent": "20", "quoteVolume": "2000000"},
        ]
        result = scanner.build_signals(rows, "SPOT", self.now)
        self.assertEqual([item["symbol"] for item in result], ["BTCUSDT"])

    def test_ignores_low_volume_and_small_moves(self):
        rows = [
            {"symbol": "LOWVOLUSDT", "lastPrice": "1", "priceChangePercent": "8", "quoteVolume": "999999"},
            {"symbol": "SMALLMOVEUSDT", "lastPrice": "1", "priceChangePercent": "2.9", "quoteVolume": "5000000"},
        ]
        self.assertEqual(scanner.build_signals(rows, "SPOT", self.now), [])

    def test_marks_up_and_down_candidates_and_expiry(self):
        rows = [
            {"symbol": "UPUSDT", "lastPrice": "2", "priceChangePercent": "5", "quoteVolume": "3000000"},
            {"symbol": "DOWNUSDT", "lastPrice": "1", "priceChangePercent": "-5.1", "quoteVolume": "3500000"},
        ]
        result = scanner.build_signals(rows, "SPOT", self.now)
        by_symbol = {item["symbol"]: item for item in result}
        self.assertEqual(by_symbol["UPUSDT"]["direction"], "BULLISH")
        self.assertEqual(by_symbol["DOWNUSDT"]["direction"], "BEARISH")
        self.assertEqual(by_symbol["UPUSDT"]["status"], "CANDIDATE_NOT_CONFIRMED")
        self.assertEqual(
            datetime.fromisoformat(by_symbol["UPUSDT"]["expires_at"]),
            self.now + timedelta(minutes=scanner.VALID_MINUTES),
        )

    def test_excludes_extreme_bullish_pumps_before_ranking(self):
        rows = [
            {"symbol": "EXTREMEUSDT", "lastPrice": "1", "priceChangePercent": "45", "quoteVolume": "9000000"},
            {"symbol": "CLEANUSDT", "lastPrice": "1", "priceChangePercent": "12", "quoteVolume": "3000000"},
        ]
        result = scanner.build_signals(rows, "SPOT", self.now)
        self.assertEqual([item["symbol"] for item in result], ["CLEANUSDT"])

    def test_bullish_spot_candidates_are_prioritized(self):
        rows = [
            {"symbol": "DUMPUSDT", "lastPrice": "1", "priceChangePercent": "-40", "quoteVolume": "5000000"},
            {"symbol": "PUMPUSDT", "lastPrice": "2", "priceChangePercent": "7", "quoteVolume": "3000000"},
            {"symbol": "RISEUSDT", "lastPrice": "3", "priceChangePercent": "5.5", "quoteVolume": "4000000"},
        ]
        result = scanner.build_signals(rows, "SPOT", self.now)
        self.assertEqual(
            [item["symbol"] for item in result],
            ["PUMPUSDT", "RISEUSDT", "DUMPUSDT"],
        )

    def test_empty_report_does_not_publish_old_signals(self):
        report = scanner.empty_report(self.now, "ERROR", "test failure")
        self.assertEqual(report["spot_signals"], [])
        self.assertEqual(report["spot_confirmed_signals"], [])
        self.assertEqual(report["confirmed_signals_found"], 0)
        self.assertEqual(report["signals_found"], 0)
        self.assertEqual(report["scanner_status"], "ERROR")


    def test_unconfirmed_candidates_remain_visible_and_labeled(self):
        candidates = [
            {"symbol": f"COIN{i}USDT", "direction": "BULLISH", "price": 1.0}
            for i in range(9)
        ]
        with patch.object(
            scanner,
            "get_trend",
            return_value={"direction": "BULLISH", "change_pct": 1.0},
        ):
            results, confirmed = scanner.confirm_spot_signals(candidates)

        self.assertEqual(results[0]["status"], "CONFIRMED_15M_1H")
        self.assertEqual(len(confirmed), 9)
        self.assertEqual(results[8]["status"], "CONFIRMED_NOT_TOP_2")
        self.assertEqual(results[8]["confirmation_status"], "CONFIRMED_NOT_TOP_2")

    def test_bullish_confirmed_signal_gets_valid_risk_levels(self):
        candidate = [{
            "symbol": "TESTUSDT",
            "direction": "BULLISH",
            "price": 100.0,
        }]
        with patch.object(
            scanner,
            "get_trend",
            return_value={"direction": "BULLISH", "change_pct": 1.0, "atr": 2.0},
        ):
            results, confirmed = scanner.confirm_spot_signals(candidate)

        self.assertEqual(len(confirmed), 1)
        signal = confirmed[0]
        self.assertEqual(signal["action_hint"], "SPOT_BUY_SETUP")
        self.assertLess(signal["stop_loss"], signal["entry_price"])
        self.assertGreater(signal["take_profit_1"], signal["entry_price"])
        self.assertGreater(signal["take_profit_2"], signal["take_profit_1"])
        self.assertEqual(signal["risk_reward_tp1"], "1:1.5")
        self.assertEqual(signal["risk_reward_tp2"], "1:2")

    def test_bearish_confirmed_signal_is_not_marked_as_spot_buy(self):
        candidate = [{
            "symbol": "TESTUSDT",
            "direction": "BEARISH",
            "price": 100.0,
        }]
        with patch.object(
            scanner,
            "get_trend",
            return_value={"direction": "BEARISH", "change_pct": -1.0, "atr": 2.0},
        ):
            results, confirmed = scanner.confirm_spot_signals(candidate)

        self.assertEqual(len(confirmed), 1)
        self.assertEqual(
            confirmed[0]["action_hint"],
            "SPOT_SELL_OR_AVOID_BUY; SHORT_REQUIRES_FUTURES",
        )
        self.assertNotIn("stop_loss", confirmed[0])

    def test_trade_plan_rejects_nonpositive_price(self):
        with self.assertRaises(ValueError):
            scanner.add_spot_trade_plan({"price": 0}, 1.0)

    def test_rejects_overextended_pump(self):
        candidate = [{
            "symbol": "PUMPUSDT",
            "direction": "BULLISH",
            "price": 1.0,
            "change_24h": 35.0,
        }]
        with patch.object(
            scanner,
            "get_trend",
            return_value={"direction": "BULLISH", "change_pct": 1.0, "atr": 0.01, "recent_resistance": 1.02},
        ):
            results, confirmed = scanner.confirm_spot_signals(candidate)

        self.assertEqual(confirmed, [])
        self.assertEqual(results[0]["confirmation_status"], "OVEREXTENDED_MOVE")

    def test_rejects_entry_too_close_to_resistance(self):
        candidate = [{
            "symbol": "RESISTUSDT",
            "direction": "BULLISH",
            "price": 100.0,
            "change_24h": 8.0,
        }]
        with patch.object(
            scanner,
            "get_trend",
            side_effect=[
                {"direction": "BULLISH", "change_pct": 1.0, "atr": 1.0, "recent_resistance": 100.3},
                {"direction": "BULLISH", "change_pct": 2.0, "atr": 1.0, "recent_resistance": 102.0},
            ],
        ):
            results, confirmed = scanner.confirm_spot_signals(candidate)

        self.assertEqual(confirmed, [])
        self.assertEqual(results[0]["confirmation_status"], "RESISTANCE_TOO_CLOSE")

    def test_trend_mismatch_is_labeled_as_unconfirmed_candidate(self):
        candidate = [{"symbol": "TESTUSDT", "direction": "BULLISH"}]
        with patch.object(
            scanner,
            "get_trend",
            side_effect=[
                {"direction": "BULLISH", "change_pct": 1.0},
                {"direction": "BEARISH", "change_pct": -1.0},
            ],
        ):
            results, confirmed = scanner.confirm_spot_signals(candidate)

        self.assertEqual(confirmed, [])
        self.assertEqual(results[0]["status"], "CANDIDATE_NOT_CONFIRMED")
        self.assertEqual(results[0]["confirmation_status"], "NOT_CONFIRMED_15M_1H")


    def test_rejects_setup_when_resistance_is_inside_tp1_distance(self):
        candidate = [{
            "symbol": "ROOMUSDT",
            "direction": "BULLISH",
            "price": 100.0,
            "change_24h": 8.0,
        }]
        with patch.object(
            scanner,
            "get_trend",
            side_effect=[
                {"direction": "BULLISH", "change_pct": 1.0, "atr": 1.0, "recent_resistance": 101.5},
                {"direction": "BULLISH", "change_pct": 2.0, "atr": 1.0, "recent_resistance": 103.0},
            ],
        ):
            results, confirmed = scanner.confirm_spot_signals(candidate)

        self.assertEqual(confirmed, [])
        self.assertEqual(results[0]["confirmation_status"], "INSUFFICIENT_RESISTANCE_ROOM")

    def test_rejects_unconfirmed_breakout_above_resistance(self):
        candidate = [{
            "symbol": "BREAKUSDT",
            "direction": "BULLISH",
            "price": 102.0,
            "change_24h": 8.0,
        }]
        with patch.object(
            scanner,
            "get_trend",
            side_effect=[
                {"direction": "BULLISH", "change_pct": 1.0, "atr": 1.0, "recent_resistance": 100.0, "breakout_confirmed": False},
                {"direction": "BULLISH", "change_pct": 2.0, "atr": 1.0, "recent_resistance": 103.0},
            ],
        ):
            results, confirmed = scanner.confirm_spot_signals(candidate)

        self.assertEqual(confirmed, [])
        self.assertEqual(results[0]["confirmation_status"], "BREAKOUT_NOT_CONFIRMED")



    def test_confirmed_spot_setup_contains_all_eight_timeframes(self):
        candidate = [{
            "symbol": "MULTITFUSDT",
            "direction": "BULLISH",
            "price": 10.0,
            "change_24h": 6.0,
            "volume_usdt": 5_000_000,
        }]
        trend = {
            "direction": "BULLISH",
            "change_pct": 0.5,
            "atr": 0.1,
            "recent_resistance": 0.0,
            "recent_support": 9.5,
            "volume_ratio": 1.4,
            "breakout_confirmed": False,
            "closed_candles_analyzed": 40,
            "candle_analysis": [{"candle_bias": "BULLISH", "close": 10.0}],
        }
        with patch.object(scanner, "get_trend", return_value=trend) as mock_trend:
            results, confirmed = scanner.confirm_spot_signals(candidate)

        self.assertEqual(mock_trend.call_count, 8)
        self.assertEqual(len(confirmed), 1)
        signal = confirmed[0]
        self.assertEqual(signal["confirmation_status"], "CONFIRMED_8_TIMEFRAMES")
        self.assertEqual(signal["timeframes_checked"], 8)
        self.assertEqual(
            set(signal["timeframe_summary"]),
            {"15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d"},
        )
        self.assertIn("candle_analysis", signal["timeframe_summary"]["15m"])


if __name__ == "__main__":
    unittest.main()
