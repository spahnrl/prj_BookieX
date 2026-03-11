import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def check_bookiex_health():
    root = PROJECT_ROOT
    print(f"📍 Project root: {root}\n")

    print("=" * 60)
    print("BOOKIEX SYSTEM HEALTH CHECK - MARCH 10, 2026")
    print("=" * 60)

    # 1. Check Directory Structure (Domain Isolation)
    required_dirs = [
        root / "data/nba/raw", root / "data/nba/view", root / "data/nba/daily",
        root / "data/ncaam/raw", root / "data/ncaam/view", root / "data/ncaam/daily",
        root / "eng/models", root / "eng/ui", root / "utils"
    ]

    print("\n[1] Directory Structure Audit:")
    for d in required_dirs:
        status = "✅" if d.exists() else "❌ MISSING"
        print(f"{status} {d}")

    # 2. Check Core Agentic Utilities
    print("\n[2] Agentic Logic Check:")
    utilities = {
        "Decorators": root / "utils/decorators.py",
        "Risk Engine": root / "utils/risk_management.py",
        "Timing Agent": root / "eng/execution/timing_agent.py"
    }
    for name, path in utilities.items():
        if path.exists():
            if name == "Decorators":
                content = path.read_text()
                if "@agent_reasoning" in content:
                    print(f"✅ {name}: Found and contains @agent_reasoning")
                else:
                    print(f"⚠️ {name}: Found, but @agent_reasoning is missing!")
            else:
                print(f"✅ {name}: Found")
        else:
            print(f"❌ {name}: {path} NOT FOUND")

    # 3. Data Integrity - NCAAM Alignment
    print("\n[3] NCAAM Data Alignment (The 'Join' Problem Check):")
    ncaam_files = {
        "Final View": root / "data/ncaam/view/final_game_view_ncaam.json",
        "Multi-Model": root / "data/ncaam/model/ncaam_games_multi_model_v1.json"
    }

    for label, path in ncaam_files.items():
        if path.exists():
            file_size = path.stat().st_size / 1024
            print(f"✅ {label}: Found ({file_size:.1f} KB)")

            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                    # Logic to count games based on your specific JSON structure
                    game_count = len(data) if isinstance(data, list) else len(data.get('games', []))
                    print(f"   📊 Sample Count: {game_count} games detected.")
            except Exception as e:
                print(f"   ❌ {label}: JSON is CORRUPT or Unreadable.")
        else:
            print(f"❌ {label}: {path} NOT FOUND")

    print("\n" + "=" * 60)
    print("END OF REPORT")
    print("=" * 60)


if __name__ == "__main__":
    check_bookiex_health()