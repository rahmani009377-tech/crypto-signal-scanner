import unittest
from datetime import datetime, timezone

import listing_watcher


class ListingWatcherTests(unittest.TestCase):
    def test_parses_utc_listing_time(self):
        start, zone = listing_watcher.parse_listing_time(
            "Trading will open at 2026-10-25 12:00 (UTC)."
        )
        self.assertEqual(start, datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(zone, "UTC")

    def test_parses_explicit_utc_offset(self):
        start, zone = listing_watcher.parse_listing_time(
            "Trading will open at 2026-10-25 12:00 (UTC+8)."
        )
        self.assertEqual(start, datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc))
        self.assertEqual(zone, "UTC+8")

    def test_does_not_guess_when_time_missing(self):
        self.assertEqual(listing_watcher.parse_listing_time("Binance will list Example Coin soon."), (None, None))

    def test_only_actual_spot_listing_titles_pass(self):
        self.assertTrue(listing_watcher.is_spot_listing_title("Binance Will List Example Coin (EXM)"))
        self.assertFalse(listing_watcher.is_spot_listing_title("Binance Futures Will List Example Coin Perpetual Contract"))
        self.assertFalse(listing_watcher.is_spot_listing_title("Binance Adds EXM/USDT Trading Pair"))
        self.assertFalse(listing_watcher.is_spot_listing_title("Introducing Example Coin on Binance Launchpool"))


if __name__ == "__main__":
    unittest.main()
