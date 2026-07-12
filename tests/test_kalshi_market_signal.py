import unittest

from eng.kalshi.kalshi_market_signal import build_matches, build_signal_view, normalize_markets


class KalshiMarketSignalTest(unittest.TestCase):
    def test_normalize_markets_uses_yes_bid_ask_midpoint(self):
        raw = {
            "schema_version": "KALSHI_RAW_MARKETS_V1",
            "markets": [
                {
                    "ticker": "KX-WNBA-LIB-LYNX",
                    "event_ticker": "KX-WNBA",
                    "title": "New York Liberty vs Minnesota Lynx",
                    "status": "open",
                    "yes_bid_dollars": "0.5400",
                    "yes_ask_dollars": "0.5800",
                    "volume_fp": "2500.00",
                    "liquidity_dollars": "1500.00",
                }
            ],
        }

        normalized = normalize_markets(raw)

        self.assertEqual(normalized["market_count"], 1)
        row = normalized["markets"][0]
        self.assertEqual(row["ticker"], "KX-WNBA-LIB-LYNX")
        self.assertEqual(row["implied_probability"], 0.56)
        self.assertEqual(row["probability_price_source"], "yes_bid_ask_mid")

    def test_build_matches_requires_both_team_sides(self):
        daily = {
            "date": "2026-07-11",
            "games": [
                {
                    "identity": {
                        "game_id": "game-1",
                        "game_date_local": "2026-07-11",
                        "home_team": "Minnesota Lynx",
                        "away_team": "New York Liberty",
                    }
                }
            ],
        }
        normalized = {
            "markets": [
                {
                    "ticker": "KX-WNBA-LIB-LYNX",
                    "market_question": "New York Liberty vs Minnesota Lynx",
                    "implied_probability": 0.56,
                    "liquidity": 1500,
                },
                {
                    "ticker": "KX-WNBA-LYNX-ONLY",
                    "market_question": "Minnesota Lynx win next game",
                    "implied_probability": 0.72,
                    "liquidity": 2000,
                },
            ]
        }

        matches = build_matches("wnba", "2026-07-11", daily, normalized)

        self.assertEqual(matches["matched_game_count"], 1)
        self.assertEqual(matches["matches"][0]["kalshi_ticker"], "KX-WNBA-LIB-LYNX")
        self.assertGreaterEqual(matches["matches"][0]["match_confidence"], 70)

    def test_signal_view_does_not_invent_bookiex_probability(self):
        daily = {
            "date": "2026-07-11",
            "games": [
                {
                    "identity": {
                        "game_id": "game-1",
                        "game_date_local": "2026-07-11",
                        "home_team": "Minnesota Lynx",
                        "away_team": "New York Liberty",
                    },
                    "model_output": {
                        "spread_pick": "New York Liberty",
                        "confidence_tier": "WATCH",
                    },
                }
            ],
        }
        normalized = {
            "markets": [
                {
                    "ticker": "KX-WNBA-LIB-LYNX",
                    "market_question": "New York Liberty vs Minnesota Lynx",
                    "implied_probability": 0.56,
                    "liquidity": 1500,
                }
            ]
        }
        matches = build_matches("wnba", "2026-07-11", daily, normalized)

        signal = build_signal_view("wnba", "2026-07-11", daily, normalized, matches)

        self.assertEqual(signal["matched_game_count"], 1)
        self.assertEqual(signal["signals"][0]["signal_label"], "KALSHI_MATCHED_NO_BOOKIEX_PROBABILITY")
        self.assertIsNone(signal["signals"][0]["bookiex_projected_probability"])


if __name__ == "__main__":
    unittest.main()
