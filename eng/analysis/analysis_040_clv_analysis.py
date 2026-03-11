"""
analysis_040_clv_analysis.py

Proxy CLV analysis using existing BookieX fields.

No pipeline changes required.

Spread CLV = Home Line Projection − spread_home_last
Total CLV  = total_last − Total Projection
"""

from pathlib import Path
import json
from collections import defaultdict

# ------------------------------------------------------------
# Resolve project root
# ------------------------------------------------------------

from configs.leagues.league_nba import FINAL_VIEW_JSON_PATH
DATA_PATH = FINAL_VIEW_JSON_PATH

# ------------------------------------------------------------
# Load data
# ------------------------------------------------------------

with open(DATA_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

games = data if isinstance(data, list) else data.get("games", [])

spread_clv = defaultdict(list)
total_clv = defaultdict(list)

# ------------------------------------------------------------
# Determine execution bucket
# ------------------------------------------------------------

def get_bucket(g):

    overlay = g.get("execution_overlay")

    if not overlay:
        return None

    if overlay.get("dual_sweet_spot"):
        return "Dual Sweet Spot"

    if overlay.get("spread_sweet_spot"):
        return "Spread Sweet Spot"

    if overlay.get("total_sweet_spot"):
        return "Total Sweet Spot"

    if overlay.get("spread_avoid") or overlay.get("total_avoid"):
        return "Avoid"

    return "Neutral"

# ------------------------------------------------------------
# Compute proxy CLV
# ------------------------------------------------------------

for g in games:

    bucket = get_bucket(g)

    if bucket is None:
        continue

    model_spread = g.get("Home Line Projection")
    market_spread = g.get("spread_home_last")

    model_total = g.get("Total Projection")
    market_total = g.get("total_last")

    if model_spread is not None and market_spread is not None:
        clv = model_spread - market_spread
        spread_clv[bucket].append(clv)

    if model_total is not None and market_total is not None:
        clv = market_total - model_total
        total_clv[bucket].append(clv)

# ------------------------------------------------------------
# Print results
# ------------------------------------------------------------

print("\n=== CLOSING LINE VALUE ANALYSIS (PROXY) ===\n")

print(
    f"{'Bucket':<20}"
    f"{'Games':<8}"
    f"{'Spread CLV':<12}"
    f"{'Total CLV':<12}"
)

print("-" * 60)

buckets = set(spread_clv.keys()) | set(total_clv.keys())

for bucket in sorted(buckets):

    s_vals = spread_clv.get(bucket, [])
    t_vals = total_clv.get(bucket, [])

    games = max(len(s_vals), len(t_vals))

    s_avg = sum(s_vals) / len(s_vals) if s_vals else 0
    t_avg = sum(t_vals) / len(t_vals) if t_vals else 0

    print(
        f"{bucket:<20}"
        f"{games:<8}"
        f"{s_avg:<12.3f}"
        f"{t_avg:<12.3f}"
    )

print()
print("Interpretation:")
print("Positive CLV = BookieX predicted where the market moved.")
print("Negative CLV = market moved against the model.")
print("This is a proxy CLV using current market lines.")
print("True CLV requires storing bet-time vs closing lines.")
print()