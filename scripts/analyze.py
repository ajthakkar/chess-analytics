"""Answer the questions in the README from data/games.parquet.

    python scripts/analyze.py

Writes results/summary.json (every number in the README and on the portfolio page),
results/regression.txt, and the charts in results/.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from statsmodels.genmod.families import Binomial
import statsmodels.formula.api as smf
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from chess_analytics.charts import draw_all  # noqa: E402

RESULTS = ROOT / "results"
SQL = ROOT / "sql"
FILTERS = {
    "all": "TRUE",
    "bullet": "time_class = 'bullet'",
    "blitz": "time_class = 'blitz'",
    "rapid": "time_class IN ('rapid', 'classical')",
}
# Near an even matchup, 1 point per 100 games is worth about 7 rating points:
# the slope of the Elo curve at a 0 gap is ln(10) / 1600 per point.
ELO_PER_POINT = 1 / (math.log(10) / 1600) / 100

SESSION_BUCKETS = """CASE
    WHEN game_in_session = 1 THEN '1'
    WHEN game_in_session <= 3 THEN '2-3'
    WHEN game_in_session <= 6 THEN '4-6'
    WHEN game_in_session <= 10 THEN '7-10'
    WHEN game_in_session <= 20 THEN '11-20'
    ELSE '21+' END"""
HOUR_BUCKETS = """CASE
    WHEN hour >= 6 AND hour < 12 THEN 'Morning (6-12)'
    WHEN hour >= 12 AND hour < 17 THEN 'Afternoon (12-5)'
    WHEN hour >= 17 AND hour < 21 THEN 'Evening (5-9)'
    WHEN hour >= 21 THEN 'Late (9-12)'
    WHEN hour < 3 THEN 'After midnight (12-3)'
    ELSE 'Very late (3-6)' END"""
STREAK = "CASE WHEN loss_streak_before >= 3 THEN '3+' ELSE CAST(loss_streak_before AS VARCHAR) END"
PREV = "coalesce(prev_result, 'first')"
# Groups smaller than this are left out: their intervals would be too wide to say anything.
MIN_GROUP = 40
STOPPED = "CASE WHEN is_last_in_session THEN 1.0 ELSE 0.0 END"

ORDERS = {
    "prev": ["first", "win", "draw", "loss"],
    "streak": ["0", "1", "2", "3+"],
    "session": ["1", "2-3", "4-6", "7-10", "11-20", "21+"],
    "hour": [
        "Morning (6-12)",
        "Afternoon (12-5)",
        "Evening (5-9)",
        "Late (9-12)",
        "After midnight (12-3)",
        "Very late (3-6)",
    ],
    "color": ["white", "black"],
    "result": ["win", "draw", "loss"],
}


def con_for(df: pd.DataFrame) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.register("games", df)
    return con


def query(con, name: str, **fmt) -> pd.DataFrame:
    return con.execute((SQL / f"{name}.sql").read_text().format(**fmt)).df()


def group_effect(
    con, key: str, where: str, order: list[str] | None = None, min_n: int = 0, value: str = "residual"
) -> list[dict]:
    """Mean of a per-game value per group with a session-clustered 95% interval, x100
    (points per 100 games for residuals, percent for 0/1 values)."""
    df = query(con, "group_effect", key=key, where=where, value=value)
    df = df[df.n >= min_n]
    rows = []
    for r in df.itertuples():
        se = float(r.se) if not pd.isna(r.se) else float("nan")
        z = r.mean / se if se > 0 else 0.0
        rows.append(
            {
                "key": str(r.grp),
                "n": int(r.n),
                "mean": round(100 * r.mean, 2),
                "lo": round(100 * (r.mean - 1.96 * se), 2),
                "hi": round(100 * (r.mean + 1.96 * se), 2),
                "p": float(2 * stats.norm.sf(abs(z))),
            }
        )
    if order:
        rank = {k: i for i, k in enumerate(order)}
        rows = sorted((r for r in rows if r["key"] in rank), key=lambda r: rank[r["key"]])
    return rows


def benjamini_hochberg(ps: list[float]) -> list[float]:
    """False discovery rate adjusted p-values (q-values)."""
    n = len(ps)
    order = np.argsort(ps)
    q = np.empty(n)
    running = 1.0
    for rank, idx in reversed(list(enumerate(order, start=1))):
        running = min(running, ps[idx] * n / rank)
        q[idx] = running
    return q.tolist()


def add_baseline(df: pd.DataFrame) -> tuple[pd.DataFrame, object]:
    """What I usually score in a game's situation: the rating gap, my color, the site and time
    control, and the year. A logistic curve fitted to all 14,000+ games.

    The plain Elo formula would be simpler, but it doesn't fit my games (see calibration.png):
    it overrates the favorite at large gaps. Opponents after a win are about 25 points weaker on
    average than after a loss, so a miscalibrated baseline alone would make losses look harmless.
    """
    d = df.copy()
    d["gap100"] = d.rating_gap / 100
    d["pool"] = d.site + ":" + d.time_class
    model = smf.glm("score ~ gap100 + C(color) + C(pool) + C(year)", data=d, family=Binomial()).fit()
    d["expected_elo"] = d.expected
    d["residual_elo"] = d.score - d.expected
    d["expected"] = model.predict(d)
    d["residual"] = d.score - d.expected
    return d, model


def openings(con, where: str, min_n: int) -> dict:
    out = {}
    for color in ["white", "black"]:
        rows = group_effect(con, "family", f"({where}) AND color = '{color}' AND family IS NOT NULL", min_n=min_n)
        for r, q in zip(rows, benjamini_hochberg([r["p"] for r in rows]) if rows else []):
            r["q"] = round(q, 4)
        out[color] = sorted(rows, key=lambda r: -r["n"])
    return out


def regression(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """All the effects at once, so one can't masquerade as another (late-night games are also
    deep-in-a-session games, for example). Least squares on the residual (points per 100 games),
    standard errors clustered by session. The baseline already accounts for rating gap, color,
    site and time control, and year; the gap enters again here in case its effect isn't linear.
    Baselines: after a win, games 2-3 of a session, evening (5-9 PM)."""
    d = df[df.game_in_session > 1].copy()  # the first game of a session has no previous result
    d["prev"] = d.prev_result
    d["session"] = pd.cut(d.game_in_session, [1, 3, 6, 10, 20, 10_000], labels=ORDERS["session"][1:]).astype(str)
    hour = d.hour
    d["tod"] = np.select(
        [(hour >= 6) & (hour < 12), (hour >= 12) & (hour < 17), (hour >= 17) & (hour < 21), hour >= 21, hour < 3],
        ORDERS["hour"][:5],
        ORDERS["hour"][5],
    )
    d["res100"] = 100 * d.residual
    d["gap100"] = d.rating_gap / 100
    model = smf.ols(
        "res100 ~ C(prev, Treatment('win')) + C(session, Treatment('2-3')) "
        "+ C(tod, Treatment('Evening (5-9)')) + gap100 + I(gap100 ** 2)",
        data=d,
    ).fit(cov_type="cluster", cov_kwds={"groups": d.session_id})
    ci = model.conf_int()
    table = pd.DataFrame({"coef": model.params, "lo": ci[0], "hi": ci[1], "p": model.pvalues})
    return table, model.summary().as_text()


def summarize(df: pd.DataFrame) -> dict:
    con = con_for(df)
    by_filter = {}
    for name, where in FILTERS.items():
        sub = query(con, "after_result", where=where)
        minutes = {r.result: float(r.median_minutes_to_next) for r in sub.itertuples()}
        stop = group_effect(con, "result", where, ORDERS["result"], value=STOPPED)
        by_filter[name] = {
            "games": int(con.execute(f"SELECT COUNT(*) FROM games WHERE {where}").fetchone()[0]),
            "prev": group_effect(con, PREV, where, ORDERS["prev"], min_n=MIN_GROUP),
            "streak": group_effect(con, STREAK, f"({where}) AND game_in_session > 1", ORDERS["streak"], min_n=MIN_GROUP),
            "session": group_effect(con, SESSION_BUCKETS, where, ORDERS["session"], min_n=MIN_GROUP),
            "hour": group_effect(con, HOUR_BUCKETS, where, ORDERS["hour"], min_n=MIN_GROUP),
            "color": group_effect(con, "color", where, ORDERS["color"]),
            "afterResult": [
                {
                    "key": r["key"],
                    "games": r["n"],
                    "stopRate": round(r["mean"] / 100, 4),
                    "lo": round(r["lo"] / 100, 4),
                    "hi": round(r["hi"] / 100, 4),
                    "minutesToNext": round(minutes.get(r["key"], float("nan")), 2),
                }
                for r in stop
            ],
            "openings": openings(con, where, min_n=150 if name == "all" else 100),
        }

    clock = query(con, "clock")
    calib = query(con, "calibration")
    sessions = df.groupby("session_id").agg(games=("score", "size"))
    span = (df.start_local.min(), df.start_local.max())
    return {
        "games": len(df),
        "sessions": int(df.session_id.nunique()),
        "sites": {k: int(v) for k, v in df.site.value_counts().items()},
        "timeClasses": {k: int(v) for k, v in df.time_class.value_counts().items()},
        "from": span[0].strftime("%Y-%m-%d"),
        "to": span[1].strftime("%Y-%m-%d"),
        "medianSessionGames": float(sessions.games.median()),
        "longestSession": int(sessions.games.max()),
        "vsEloFormula": round(100 * float(df.residual_elo.mean()), 2),
        "eloPerPoint": round(ELO_PER_POINT, 2),
        "calibration": [
            {
                "gap": int(r.gap),
                "games": int(r.games),
                "elo": round(r.expected_elo, 4),
                "baseline": round(r.baseline, 4),
                "actual": round(r.actual, 4),
            }
            for r in calib.itertuples()
        ],
        "clock": [
            {
                "timeClass": r.time_class,
                "games": int(r.games),
                "wonOnTime": round(float(r.won_on_time), 4),
                "lostOnTime": round(float(r.lost_on_time), 4),
                "flagBalance": round(float(r.flag_balance), 2),
                "shareOfLossesOnTime": round(float(r.share_of_losses_on_time), 4),
                "shareOfWinsOnTime": round(float(r.share_of_wins_on_time), 4),
            }
            for r in clock.itertuples()
        ],
        "firstMoveWhite": sorted(
            group_effect(con, "split_part(first_moves, ' ', 1)", "color = 'white'", min_n=100), key=lambda r: -r["n"]
        ),
        "byFilter": by_filter,
    }


def main() -> None:
    df = pd.read_parquet(ROOT / "data" / "games.parquet")
    df = df[df.time_class.isin(["bullet", "blitz", "rapid", "classical"])]
    df, baseline = add_baseline(df)
    RESULTS.mkdir(exist_ok=True)

    summary = summarize(df)
    table, text = regression(df)
    (RESULTS / "regression.txt").write_text(
        "Baseline model (what I usually score):\n" + baseline.summary().as_text() + "\n\n\nEffects model:\n" + text
    )
    summary["regression"] = [
        {"term": t, "coef": round(r.coef, 2), "lo": round(r.lo, 2), "hi": round(r.hi, 2), "p": float(r.p)}
        for t, r in table.iterrows()
        if t != "Intercept"
    ]
    summary["baselineGapSlope"] = round(float(baseline.params["gap100"]), 4)
    summary["updated"] = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2))
    draw_all(summary, RESULTS)

    a = summary["byFilter"]["all"]
    print(f"{summary['games']:,} games in {summary['sessions']:,} sessions, {summary['from']} to {summary['to']}")
    print(f"vs the Elo formula: {summary['vsEloFormula']:+.2f} per 100 games")
    for name in ["prev", "streak", "session", "hour", "color"]:
        print(name, [(r["key"], r["mean"], r["lo"], r["hi"], r["n"]) for r in a[name]])
    print("stop:", a["afterResult"])
    print(table.round(2).to_string())


if __name__ == "__main__":
    main()
