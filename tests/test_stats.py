"""The SQL statistics are checked against a plain numpy version of the same math."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyze  # noqa: E402


def clustered_mean_se(y: np.ndarray, clusters: np.ndarray) -> tuple[float, float]:
    """Mean and session-clustered standard error, written out by hand."""
    mean = y.mean()
    groups = pd.Series(y - mean).groupby(clusters).sum().to_numpy()
    g = len(groups)
    se = np.sqrt((groups**2).sum() * g / (g - 1)) / len(y)
    return mean, se


@pytest.fixture
def games():
    rng = np.random.default_rng(7)
    n = 600
    session = np.repeat(np.arange(120), 5)
    shock = rng.normal(0, 0.15, 120)[session]  # a "bad night" shared by every game in a session
    residual = np.clip(rng.normal(0.02, 0.4, n) + shock, -1, 1)
    return pd.DataFrame(
        {
            "session_id": session,
            "residual": residual,
            "color": rng.choice(["white", "black"], n),
            "time_class": "bullet",
        }
    )


def test_group_effect_matches_numpy(games):
    con = analyze.con_for(games)
    rows = {r["key"]: r for r in analyze.group_effect(con, "color", "TRUE")}
    for color in ["white", "black"]:
        sub = games[games.color == color]
        mean, se = clustered_mean_se(sub.residual.to_numpy(), sub.session_id.to_numpy())
        r = rows[color]
        assert r["n"] == len(sub)
        assert r["mean"] == pytest.approx(100 * mean, abs=0.01)
        assert r["lo"] == pytest.approx(100 * (mean - 1.96 * se), abs=0.01)
        assert r["hi"] == pytest.approx(100 * (mean + 1.96 * se), abs=0.01)


def test_clustering_widens_the_interval(games):
    """Games from the same night move together, so treating them as independent would overstate
    certainty. The clustered interval should be wider than the naive one."""
    con = analyze.con_for(games)
    r = analyze.group_effect(con, "'all'", "TRUE")[0]
    naive_se = games.residual.std(ddof=1) / np.sqrt(len(games))
    assert (r["hi"] - r["lo"]) / 100 > 2 * 1.96 * naive_se


def test_benjamini_hochberg():
    # Worked example: p = [0.01, 0.04, 0.03, 0.20] -> q = [0.04, 0.0533, 0.0533, 0.20]
    q = analyze.benjamini_hochberg([0.01, 0.04, 0.03, 0.20])
    assert q == pytest.approx([0.04, 0.16 / 3, 0.16 / 3, 0.20])
    assert all(qi >= pi for qi, pi in zip(q, [0.01, 0.04, 0.03, 0.20]))
