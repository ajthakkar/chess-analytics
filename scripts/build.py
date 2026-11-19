"""Build data/games.parquet: one row per rated game from both sites, ready for analysis.

    python scripts/build.py

Adds pre-game ratings, the Elo expected score, local time, sessions, and opening families.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chess_analytics.parse import (  # noqa: E402
    chesscom_game,
    expected_score,
    family_from_slug,
    lichess_game,
    opening_family,
)
from chess_analytics.sessions import add_sessions, to_local  # noqa: E402

RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "games.parquet"
ACCOUNTS = json.loads((ROOT / "accounts.json").read_text())


def load() -> pd.DataFrame:
    rows = []
    for f in sorted((RAW / "chesscom").glob("*.json")):
        for g in json.loads(f.read_text(encoding="utf-8")).get("games", []):
            if (row := chesscom_game(g, ACCOUNTS["chesscom"])) is not None:
                rows.append(row)
    with (RAW / "lichess.ndjson").open(encoding="utf-8") as fh:
        seen = set()
        for line in fh:
            if not line.strip():
                continue
            g = json.loads(line)
            if g["id"] in seen:
                continue
            seen.add(g["id"])
            if (row := lichess_game(g, ACCOUNTS["lichess"])) is not None:
                rows.append(row)
    return pd.DataFrame(rows)


def chesscom_pre_game(df: pd.DataFrame) -> pd.DataFrame:
    """Chess.com archives report ratings after each game. A game's pre-game rating is the
    post-game rating of my previous game in the same time class; my rating change is the
    difference. The opponent's pre-game rating is estimated as their post-game rating minus
    the mirror of my change (rating systems move both players by about the same amount)."""
    cc = df[df.site == "chesscom"].sort_values("end_utc").copy()
    prev = cc.groupby("time_class").my_rating_post.shift(1)
    cc["rating_change"] = cc.my_rating_post - prev
    cc["my_rating"] = prev
    cc["opp_rating"] = cc.opp_rating_post + cc.rating_change
    # Long breaks or rating floors can make the change meaningless; keep it only when plausible.
    bad = cc.rating_change.abs() > 60
    cc.loc[bad, ["my_rating", "opp_rating", "rating_change"]] = None
    df = df.copy()
    df.loc[cc.index, ["my_rating", "opp_rating", "rating_change"]] = cc[["my_rating", "opp_rating", "rating_change"]]
    return df


def main() -> None:
    df = load()
    df = chesscom_pre_game(df)
    df = df.dropna(subset=["my_rating", "opp_rating"]).copy()
    for col in ["my_rating", "opp_rating", "rating_change", "base_s", "inc_s"]:
        df[col] = pd.to_numeric(df[col])
    df["rating_gap"] = df.opp_rating - df.my_rating
    df["expected"] = [expected_score(m, o) for m, o in zip(df.my_rating, df.opp_rating)]
    df["residual"] = df.score - df.expected

    # One opening vocabulary for both sites: Lichess names its openings, Chess.com mostly
    # shares ECO codes, so Chess.com games take the family Lichess uses most for that code.
    df["family"] = df.opening_name.map(opening_family)
    by_eco = df.dropna(subset=["family", "eco"]).groupby("eco").family.agg(lambda s: s.value_counts().index[0])
    missing = df.family.isna()
    df.loc[missing, "family"] = df.loc[missing, "eco"].map(by_eco)
    still = df.family.isna()
    df.loc[still, "family"] = df.loc[still, "opening_slug"].map(family_from_slug)

    df = to_local(df)
    df = add_sessions(df)
    keep = [
        "site", "game_id", "start_utc", "end_utc", "start_local", "hour", "weekday", "year",
        "time_class", "base_s", "inc_s", "color", "my_rating", "opp_rating", "rating_gap",
        "rating_change", "result", "score", "expected", "residual", "termination", "plies",
        "my_clock_end", "opp_clock_end", "eco", "family", "first_moves",
        "session_id", "game_in_session", "session_games", "prev_result", "minutes_since_prev",
        "is_last_in_session", "loss_streak_before",
    ]
    df = df[keep].sort_values("start_utc").reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    print(df.groupby(["site", "time_class"]).size().to_string())
    print(f"{len(df):,} games, {df.session_id.nunique():,} sessions -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
