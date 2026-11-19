from datetime import datetime, timezone

import pandas as pd
import pytest

from chess_analytics.parse import (
    chesscom_game,
    end_clocks,
    expected_score,
    family_from_slug,
    lichess_game,
    opening_family,
    parse_time_control,
    pgn_clocks,
    pgn_moves,
)
from chess_analytics.sessions import add_sessions, to_local

PGN = """[Event "Live Chess"]
[UTCDate "2026.11.05"]
[UTCTime "04:01:13"]
[ECO "A60"]
[ECOUrl "https://www.chess.com/openings/Benoni-Defense-Modern-Variation...6.Nf3"]

1. d4 {[%clk 0:02:59.1]} 1... Nf6 {[%clk 0:02:57.6]} 2. Nf3 {[%clk 0:02:58.6]} 0-1"""


def cc(white_result, black_result):
    """A Chess.com archive record where I'm Black."""
    return {
        "url": "https://www.chess.com/game/live/1",
        "time_control": "180",
        "end_time": 1793851659,
        "rated": True,
        "rules": "chess",
        "time_class": "blitz",
        "white": {"username": "them", "rating": 2489, "result": white_result},
        "black": {"username": "me", "rating": 2511, "result": black_result},
        "pgn": PGN,
    }


def test_time_control():
    assert parse_time_control("180+2") == (180, 2)
    assert parse_time_control("60") == (60, 0)


def test_clocks_and_moves():
    assert pgn_clocks(PGN) == [179.1, 177.6, 178.6]
    assert pgn_moves(PGN) == ["d4", "Nf6"]
    # White moves on even plies: white's last clock is 178.6, black's is 177.6.
    assert end_clocks([179.1, 177.6, 178.6], "white") == (178.6, 177.6)
    assert end_clocks([179.1, 177.6, 178.6], "black") == (177.6, 178.6)
    assert end_clocks([], "white") == (None, None)


@pytest.mark.parametrize(
    "white, black, result, termination",
    [
        ("checkmated", "win", "win", "checkmate"),
        ("timeout", "win", "win", "time"),
        ("win", "resigned", "loss", "resign"),
        ("win", "abandoned", "loss", "abandon"),
        ("repetition", "repetition", "draw", "draw"),
        ("timevsinsufficient", "timevsinsufficient", "draw", "draw"),
    ],
)
def test_chesscom_results(white, black, result, termination):
    row = chesscom_game(cc(white, black), "ME")
    assert row["color"] == "black"
    assert (row["result"], row["termination"]) == (result, termination)
    assert row["start_utc"] == datetime(2026, 11, 5, 4, 1, 13, tzinfo=timezone.utc)
    assert row["eco"] == "A60"


def test_chesscom_skips_variants_and_unrated():
    assert chesscom_game(cc("win", "checkmated") | {"rules": "bughouse"}, "me") is None
    assert chesscom_game(cc("win", "checkmated") | {"rated": False}, "me") is None
    assert chesscom_game(cc("win", "checkmated") | {"time_class": "daily"}, "me") is None


def lichess(status, winner, me="white"):
    them = "black" if me == "white" else "white"
    g = {
        "id": "abc",
        "rated": True,
        "variant": "standard",
        "perf": "bullet",
        "status": status,
        "createdAt": 1_700_000_000_000,
        "lastMoveAt": 1_700_000_060_000,
        "players": {
            me: {"user": {"id": "me"}, "rating": 2500, "ratingDiff": 6},
            them: {"user": {"id": "them"}, "rating": 2450, "ratingDiff": -6},
        },
        "moves": "e4 c5 Nf3",
        "clocks": [6000, 6000, 5900],
        "clock": {"initial": 60, "increment": 0},
        "opening": {"eco": "B27", "name": "Sicilian Defense: Hyperaccelerated Dragon"},
    }
    if winner:
        g["winner"] = winner
    return g


def test_lichess_results():
    row = lichess_game(lichess("outoftime", "white"), "Me")
    assert (row["result"], row["termination"], row["score"]) == ("win", "time", 1.0)
    assert (row["my_rating"], row["opp_rating"], row["rating_change"]) == (2500, 2450, 6)
    assert row["my_clock_end"] == 59.0 and row["opp_clock_end"] == 60.0
    assert row["first_moves"] == "e4 c5"
    assert lichess_game(lichess("mate", "white", me="black"), "me")["result"] == "loss"
    draw = lichess_game(lichess("stalemate", None), "me")
    assert (draw["result"], draw["score"]) == ("draw", 0.5)
    assert lichess_game(lichess("aborted", None), "me") is None


def test_expected_score():
    assert expected_score(2000, 2000) == pytest.approx(0.5)
    assert expected_score(2400, 2000) == pytest.approx(10 / 11)
    assert expected_score(2000, 2400) + expected_score(2400, 2000) == pytest.approx(1)


def test_opening_names():
    assert opening_family("Sicilian Defense: Najdorf Variation, English Attack") == "Sicilian Defense"
    assert opening_family(None) is None
    assert family_from_slug("Sicilian-Defense-Najdorf-Variation-6.Be3") == "Sicilian Defense"
    assert family_from_slug("Benoni-Defense-Modern-Variation...6.Nf3") == "Benoni Defense"
    assert family_from_slug("Ruy-Lopez-Opening-Berlin-Defense") == "Ruy Lopez Opening"


def games(times, results):
    """times: list of (start minute, end minute)."""
    t0 = pd.Timestamp("2026-01-01 18:00", tz="UTC")
    return pd.DataFrame(
        {
            "start_utc": [t0 + pd.Timedelta(minutes=s) for s, _ in times],
            "end_utc": [t0 + pd.Timedelta(minutes=e) for _, e in times],
            "result": results,
        }
    )


def test_sessions_split_on_long_breaks():
    df = add_sessions(games([(0, 3), (4, 7), (8, 11), (60, 63), (64, 67)], ["loss", "loss", "win", "loss", "win"]))
    assert df.session_id.tolist() == [1, 1, 1, 2, 2]
    assert df.game_in_session.tolist() == [1, 2, 3, 1, 2]
    assert df.session_games.tolist() == [3, 3, 3, 2, 2]
    assert df.prev_result.tolist()[1:3] == ["loss", "loss"]
    assert pd.isna(df.prev_result[3])  # nothing carries over from the last session
    assert df.loss_streak_before.tolist() == [0, 1, 2, 0, 1]
    assert df.is_last_in_session.tolist() == [False, False, True, False, True]


def test_local_time_follows_the_move_to_columbus():
    df = to_local(
        pd.DataFrame({"start_utc": [pd.Timestamp("2026-01-10 03:00", tz="UTC"), pd.Timestamp("2026-10-10 03:00", tz="UTC")]})
    )
    assert df.hour.tolist() == [21, 23]  # 9 PM Central in January, 11 PM Eastern in October
