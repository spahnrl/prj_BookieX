import unittest

from eng.normalization import load_default_registry


class ConfigDrivenNormalizationTest(unittest.TestCase):
    def test_default_registry_discovers_enabled_leagues(self):
        registry = load_default_registry()
        self.assertEqual(
            registry.keys(),
            [
                "americanfootball_ncaaf",
                "americanfootball_nfl",
                "baseball_mlb",
                "basketball_nba",
                "basketball_ncaab",
                "basketball_wnba",
                "icehockey_nhl",
            ],
        )

    def test_nba_odds_api_snapshot_normalizes_events_and_markets(self):
        registry = load_default_registry(active_sport_keys=["basketball_nba"])
        self.assertEqual(registry.keys(), ["basketball_nba"])

        raw_events = [
            {
                "id": "evt_spurs_knicks",
                "sport_key": "basketball_nba",
                "commence_time": "2026-06-10T00:30:00Z",
                "home_team": "NY Knicks",
                "away_team": "San Antonio Spurs",
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "title": "DraftKings",
                        "last_update": "2026-06-09T23:45:00Z",
                        "markets": [
                            {
                                "key": "h2h",
                                "last_update": "2026-06-09T23:45:00Z",
                                "outcomes": [
                                    {"name": "NY Knicks", "price": -130},
                                    {"name": "San Antonio Spurs", "price": 110}
                                ]
                            },
                            {
                                "key": "spreads",
                                "last_update": "2026-06-09T23:45:00Z",
                                "outcomes": [
                                    {"name": "NY Knicks", "price": -110, "point": -2.5},
                                    {"name": "San Antonio Spurs", "price": -110, "point": 2.5}
                                ]
                            },
                            {
                                "key": "totals",
                                "last_update": "2026-06-09T23:45:00Z",
                                "outcomes": [
                                    {"name": "Over", "price": -108, "point": 220.5},
                                    {"name": "Under", "price": -112, "point": 220.5}
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        normalized = registry.normalize_snapshot(
            "basketball_nba",
            raw_events,
            captured_at_utc="2026-06-09T23:50:00Z",
        )

        self.assertEqual(normalized["league_key"], "nba")
        self.assertEqual(len(normalized["events"]), 1)
        self.assertEqual(normalized["events"][0]["home_team"], "New York Knicks")
        self.assertEqual(normalized["events"][0]["home_team_key"], "NYK")
        self.assertEqual(len(normalized["market_rows"]), 6)
        self.assertEqual(
            {row["canonical_outcome"] for row in normalized["market_rows"]},
            {"HOME", "AWAY", "OVER", "UNDER"},
        )

    def test_nfl_odds_api_snapshot_normalizes_events_and_markets(self):
        registry = load_default_registry(active_sport_keys=["americanfootball_nfl"])
        self.assertEqual(registry.keys(), ["americanfootball_nfl"])

        raw_events = [
            {
                "id": "evt_chiefs_broncos",
                "sport_key": "americanfootball_nfl",
                "commence_time": "2025-09-08T00:20:00Z",
                "home_team": "Kansas City Chiefs",
                "away_team": "Denver Broncos",
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "title": "DraftKings",
                        "last_update": "2025-09-07T20:00:00Z",
                        "markets": [
                            {
                                "key": "h2h",
                                "last_update": "2025-09-07T20:00:00Z",
                                "outcomes": [
                                    {"name": "Kansas City Chiefs", "price": -180},
                                    {"name": "Denver Broncos", "price": 150}
                                ]
                            },
                            {
                                "key": "spreads",
                                "last_update": "2025-09-07T20:00:00Z",
                                "outcomes": [
                                    {"name": "Kansas City Chiefs", "price": -110, "point": -3.5},
                                    {"name": "Denver Broncos", "price": -110, "point": 3.5}
                                ]
                            },
                            {
                                "key": "totals",
                                "last_update": "2025-09-07T20:00:00Z",
                                "outcomes": [
                                    {"name": "Over", "price": -108, "point": 47.5},
                                    {"name": "Under", "price": -112, "point": 47.5}
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        normalized = registry.normalize_snapshot(
            "americanfootball_nfl",
            raw_events,
            captured_at_utc="2025-09-07T20:05:00Z",
        )

        self.assertEqual(normalized["league_key"], "nfl")
        self.assertEqual(len(normalized["events"]), 1)
        self.assertEqual(normalized["events"][0]["home_team"], "Kansas City Chiefs")
        self.assertEqual(normalized["events"][0]["home_team_key"], "KC")
        self.assertEqual(len(normalized["market_rows"]), 6)

    def test_ncaaf_odds_api_snapshot_normalizes_events_and_markets(self):
        registry = load_default_registry(active_sport_keys=["americanfootball_ncaaf"])
        self.assertEqual(registry.keys(), ["americanfootball_ncaaf"])

        raw_events = [
            {
                "id": "evt_texas_ou",
                "sport_key": "americanfootball_ncaaf",
                "commence_time": "2025-10-11T19:30:00Z",
                "home_team": "Texas Longhorns",
                "away_team": "Oklahoma Sooners",
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "title": "DraftKings",
                        "last_update": "2025-10-11T12:00:00Z",
                        "markets": [
                            {
                                "key": "h2h",
                                "last_update": "2025-10-11T12:00:00Z",
                                "outcomes": [
                                    {"name": "Texas Longhorns", "price": -140},
                                    {"name": "Oklahoma Sooners", "price": 120}
                                ]
                            },
                            {
                                "key": "spreads",
                                "last_update": "2025-10-11T12:00:00Z",
                                "outcomes": [
                                    {"name": "Texas Longhorns", "price": -110, "point": -2.5},
                                    {"name": "Oklahoma Sooners", "price": -110, "point": 2.5}
                                ]
                            },
                            {
                                "key": "totals",
                                "last_update": "2025-10-11T12:00:00Z",
                                "outcomes": [
                                    {"name": "Over", "price": -110, "point": 56.5},
                                    {"name": "Under", "price": -110, "point": 56.5}
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        normalized = registry.normalize_snapshot(
            "americanfootball_ncaaf",
            raw_events,
            captured_at_utc="2025-10-11T12:05:00Z",
        )

        self.assertEqual(normalized["league_key"], "ncaaf")
        self.assertEqual(len(normalized["events"]), 1)
        self.assertEqual(normalized["events"][0]["home_team"], "Texas Longhorns")
        self.assertEqual(normalized["events"][0]["home_team_key"], "TEXAS_LONGHORNS")
        self.assertEqual(len(normalized["market_rows"]), 6)


if __name__ == "__main__":
    unittest.main()
