import unittest
from datetime import datetime, timezone, timedelta

import scanner


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

    def test_filters_non_usdt_and_non_ascii_symbols(self):
        rows = [
            {"symbol": "BTCUSDT", "lastPrice": "100", "priceChangePercent": "6", "quoteVolume": "2000000"},
            {"symbol": "ETHBTC", "lastPrice": "1", "priceChangePercent": "20", "quoteVolume": "2000000"},
            {"symbol": "牛来USDT", "lastPrice": "1", "priceChangePercent": "20", "quoteVolume": "2000000"},
        ]
        result = scanner.build_signals(rows, "SPOT", self.now)
        self.assertEqual([item["symbol"] for item in result], ["BTCUSDT"])

    def test_ignores_low_volume_and_small_moves(self):
        rows = [
            {"symbol": "LOWVOLUSDT", "lastPrice": "1", "priceChangePercent": "8", "quoteVolume": "999999"},
            {"symbol": "SMALLMOVEUSDT", "lastPrice": "1", "priceChangePercent": "4.9", "quoteVolume": "5000000"},
        ]
        self.assertEqual(scanner.build_signals(rows, "SPOT", self.now), [])

    def test_marks_up_and_down_candidates_and_expiry(self):
        rows = [
            {"symbol": "UPUSDT", "lastPrice": "2", "priceChangePercent": "5", "quoteVolume": "1000000"},
            {"symbol": "DOWNUSDT", "lastPrice": "1", "priceChangePercent": "-5.1", "quoteVolume": "1500000"},
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

    def test_empty_report_does_not_publish_old_signals(self):
        report = scanner.empty_report(self.now, "ERROR", "test failure")
        self.assertEqual(report["spot_signals"], [])
        self.assertEqual(report["futures_signals"], [])
        self.assertEqual(report["signals_found"], 0)
        self.assertEqual(report["scanner_status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
