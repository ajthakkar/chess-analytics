"""Charts for the README. One accent color; intervals that cross zero are drawn hollow."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

INK = "#1f2328"
MUTED = "#656d76"
GRID = "#d8dee4"
ACCENT = "#2f6f3e"
BG = "#ffffff"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.edgecolor": GRID,
        "axes.labelcolor": MUTED,
        "xtick.color": MUTED,
        "ytick.color": INK,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "figure.facecolor": BG,
        "axes.facecolor": BG,
        "savefig.facecolor": BG,
    }
)


def _title(fig, title: str, subtitle: str) -> None:
    fig.text(0.02, 0.97, title, fontsize=13, fontweight="bold", color=INK, va="top")
    fig.text(0.02, 0.905, subtitle, fontsize=9.5, color=MUTED, va="top")


def _save(fig, out: Path, name: str) -> None:
    for ext in ("png", "svg"):
        fig.savefig(out / f"{name}.{ext}", dpi=160)
    plt.close(fig)


def dot_ci(rows: list[dict], labels: dict[str, str] | None, title: str, subtitle: str, out: Path, name: str) -> None:
    """Horizontal dot + 95% interval chart of residuals (points per 100 games vs expectation)."""
    labels = labels or {}
    h = 1.45 + 0.4 * len(rows)
    fig, ax = plt.subplots(figsize=(7.6, h))
    fig.subplots_adjust(left=0.30, right=0.97, top=1 - 0.78 / h, bottom=0.62 / h)
    ys = list(range(len(rows)))[::-1]
    for y, r in zip(ys, rows):
        sig = r["q"] < 0.05 if "q" in r else (r["lo"] > 0 or r["hi"] < 0)
        ax.plot([r["lo"], r["hi"]], [y, y], color=ACCENT, lw=2, solid_capstyle="round")
        ax.plot(r["mean"], y, "o", ms=8, mfc=ACCENT if sig else BG, mec=ACCENT, mew=2)
        ax.text(max(r["hi"], r["mean"]) + 0.25, y, f"{r['mean']:+.1f}", va="center", fontsize=9, color=INK)
    ax.axvline(0, color=INK, lw=1)
    ax.set_yticks(ys, [f"{labels.get(r['key'], r['key'])}  ({r['n']:,})" for r in rows])
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.set_xlabel("points per 100 games above (+) or below (-) my baseline")
    lo = min(r["lo"] for r in rows)
    hi = max(r["hi"] for r in rows)
    pad = (hi - lo) * 0.15 + 0.5
    ax.set_xlim(min(lo, 0) - pad, max(hi, 0) + pad * 1.6)
    _title(fig, title, subtitle)
    _save(fig, out, name)


def calibration(rows: list[dict], out: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    fig.subplots_adjust(left=0.1, right=0.97, top=0.8, bottom=0.14)
    gaps = [r["gap"] for r in rows]
    ax.plot(gaps, [r["elo"] for r in rows], color=MUTED, lw=2, ls="--", label="Elo formula")
    ax.plot(gaps, [r["baseline"] for r in rows], color=ACCENT, lw=2, label="Fitted baseline")
    ax.plot(gaps, [r["actual"] for r in rows], "o", color=ACCENT, mfc=BG, mew=2, ms=6, label="What actually happened")
    ax.set_xlabel("opponent's rating minus mine")
    ax.set_ylabel("my score")
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.grid(color=GRID, lw=0.6)
    ax.legend(frameon=False, loc="upper right")
    _title(
        fig,
        "The Elo formula overrates big rating gaps",
        "Average score by rating gap (30+ games per point). Every comparison uses the fitted baseline.",
    )
    _save(fig, out, "calibration")


def stop_rate(rows: list[dict], out: Path) -> None:
    order = {"win": 0, "draw": 1, "loss": 2}
    rows = sorted(rows, key=lambda r: order[r["key"]])
    fig, ax = plt.subplots(figsize=(7.6, 2.8))
    fig.subplots_adjust(left=0.16, right=0.95, top=0.66, bottom=0.2)
    ys = list(range(len(rows)))[::-1]
    for y, r in zip(ys, rows):
        ax.barh(y, r["stopRate"], color=ACCENT, height=0.55)
        ax.plot([r["lo"], r["hi"]], [y, y], color=INK, lw=1.2)
        ax.text(r["hi"] + 0.006, y, f"{r['stopRate']:.0%}  ·  next game in {r['minutesToNext']:.1f} min",
                va="center", fontsize=9, color=INK)
    ax.set_yticks(ys, [f"After a {r['key']}" for r in rows])
    ax.tick_params(axis="y", length=0)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xlim(0, max(r["stopRate"] for r in rows) * 1.9)
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    _title(fig, "Do I stop after a loss?", "Chance a game is my last of the session (with 95% interval), and the median wait before the next one.")
    _save(fig, out, "stop_rate")


def clock(rows: list[dict], out: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.6, 3.0))
    fig.subplots_adjust(left=0.13, right=0.95, top=0.68, bottom=0.2)
    ys = list(range(len(rows)))[::-1]
    for y, r in zip(ys, rows):
        ax.barh(y + 0.17, 100 * r["wonOnTime"], height=0.32, color=ACCENT)
        ax.barh(y - 0.17, 100 * r["lostOnTime"], height=0.32, color=BG, edgecolor=ACCENT, hatch="////", lw=1)
        ax.text(100 * max(r["wonOnTime"], r["lostOnTime"]) + 0.5, y,
                f"net {r['flagBalance']:+.1f} per 100 games", va="center", fontsize=9, color=INK)
    ax.set_yticks(ys, [r["timeClass"].title() for r in rows])
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("games per 100 decided on time")
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.set_xlim(0, 100 * max(max(r["wonOnTime"], r["lostOnTime"]) for r in rows) * 1.7)
    from matplotlib.patches import Patch

    ax.legend(
        handles=[Patch(color=ACCENT, label="I won on time"),
                 Patch(facecolor=BG, edgecolor=ACCENT, hatch="////", label="I lost on time")],
        frameon=False, loc="lower right", fontsize=9,
    )
    _title(fig, "The clock is on my side", "Games won and lost on time, by time control.")
    _save(fig, out, "clock")


def draw_all(summary: dict, out: Path) -> None:
    a = summary["byFilter"]["all"]
    dot_ci(
        a["prev"],
        {"first": "First game of a session", "win": "After a win", "draw": "After a draw", "loss": "After a loss"},
        "Tilt: how I play after a loss",
        "Score vs. my baseline, by the previous game's result. Bars are 95% intervals; hollow dots overlap zero.",
        out,
        "tilt",
    )
    dot_ci(
        a["streak"],
        {"0": "No loss before it", "1": "1 loss in a row", "2": "2 losses in a row", "3+": "3+ losses in a row"},
        "Losing streaks",
        "Games after the first of a session, by how many losses came right before.",
        out,
        "streak",
    )
    dot_ci(
        a["session"],
        {k: f"Game {k}" for k in ["1", "2-3", "4-6", "7-10", "11-20", "21+"]},
        "Fatigue: deep into a session",
        "A session is a run of games with no break over 30 minutes.",
        out,
        "session",
    )
    dot_ci(a["hour"], None, "Time of day", "Local time (Central until Aug 2026, then Eastern).", out, "hour")
    for color in ["white", "black"]:
        rows = a["openings"][color][:12]
        if rows:
            dot_ci(
                rows,
                None,
                f"Openings as {color.title()}",
                "Score vs. my baseline (which already includes my color). Families with 150+ games; filled = significant after correcting for testing many.",
                out,
                f"openings_{color}",
            )
    calibration(summary["calibration"], out)
    stop_rate(a["afterResult"], out)
    clock(summary["clock"], out)
