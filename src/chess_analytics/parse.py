"""Turn raw Chess.com and Lichess game records into one row per game, from my side of the board.

Only what the analysis needs is kept. Opponents' usernames are dropped.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

# How a decisive game ended, from the loser's side, in one vocabulary for both sites.
CHESSCOM_LOSS = {
    "checkmated": "checkmate",
    "resigned": "resign",
    "timeout": "time",
    "abandoned": "abandon",
    "lose": "other",
}
CHESSCOM_DRAW = {"agreed", "repetition", "stalemate", "insufficient", "50move", "timevsinsufficient"}
LICHESS_STATUS = {
    "mate": "checkmate",
    "resign": "resign",
    "outoftime": "time",
    "timeout": "abandon",  # the player left the game and the opponent claimed the win
    "draw": "draw",
    "stalemate": "draw",
    "cheat": "other",
}
SKIP_LICHESS = {"aborted", "noStart", "unknownFinish", "variantEnd", "created", "started"}

_CLK = re.compile(r"\[%clk (\d+):(\d+):(\d+(?:\.\d+)?)\]")
_TAG = re.compile(r'^\[(\w+) "(.*)"\]$', re.M)
_MOVE_NUMBER = re.compile(r"^\d+\.(\.\.)?$")


def score_for(result: str) -> float:
    return {"win": 1.0, "draw": 0.5, "loss": 0.0}[result]


def parse_time_control(tc: str) -> tuple[int, int]:
    """'180+2' -> (180, 2); '60' -> (60, 0)."""
    base, _, inc = tc.partition("+")
    return int(base), int(inc or 0)


def pgn_clocks(pgn: str) -> list[float]:
    """Seconds left after each ply, from Chess.com's [%clk h:mm:ss.s] comments."""
    return [int(h) * 3600 + int(m) * 60 + float(s) for h, m, s in _CLK.findall(pgn)]


def pgn_moves(pgn: str, n: int = 2) -> list[str]:
    """The first n moves in SAN, skipping tags, move numbers, and comments."""
    body = pgn.split("\n\n", 1)[-1]
    body = re.sub(r"\{[^}]*\}", " ", body)
    moves = [t for t in body.split() if not _MOVE_NUMBER.match(t) and t not in {"1-0", "0-1", "1/2-1/2", "*"}]
    return moves[:n]


def end_clocks(clocks: list[float], color: str) -> tuple[float | None, float | None]:
    """(my clock, opponent's clock) after each side's last move. White moves on even plies."""
    mine_idx = 0 if color == "white" else 1
    mine = clocks[mine_idx::2]
    theirs = clocks[1 - mine_idx :: 2]
    return (mine[-1] if mine else None, theirs[-1] if theirs else None)


def chesscom_game(g: dict, user: str) -> dict | None:
    if g.get("rules") != "chess" or not g.get("rated") or g.get("time_class") not in {"bullet", "blitz", "rapid"}:
        return None
    color = "white" if g["white"]["username"].lower() == user.lower() else "black"
    me, opp = g[color], g["black" if color == "white" else "white"]
    if me["result"] == "win":
        result, termination = "win", CHESSCOM_LOSS.get(opp["result"], "other")
    elif me["result"] in CHESSCOM_DRAW:
        result, termination = "draw", "draw"
    else:
        result, termination = "loss", CHESSCOM_LOSS.get(me["result"], "other")

    pgn = g.get("pgn", "")
    tags = dict(_TAG.findall(pgn))
    base, inc = parse_time_control(g["time_control"])
    end = datetime.fromtimestamp(g["end_time"], tz=timezone.utc)
    start = end
    if "UTCDate" in tags and "UTCTime" in tags:
        start = datetime.strptime(f'{tags["UTCDate"]} {tags["UTCTime"]}', "%Y.%m.%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    clocks = pgn_clocks(pgn)
    my_clock, opp_clock = end_clocks(clocks, color)
    eco_url = tags.get("ECOUrl", g.get("eco", "")) or ""
    return {
        "site": "chesscom",
        "game_id": g["url"].rsplit("/", 1)[-1],
        "start_utc": start,
        "end_utc": end,
        "time_class": g["time_class"],
        "base_s": base,
        "inc_s": inc,
        "color": color,
        # Chess.com reports each player's rating after the game; build.py turns it into pre-game.
        "my_rating_post": me["rating"],
        "opp_rating_post": opp["rating"],
        "my_rating": None,
        "opp_rating": None,
        "rating_change": None,
        "result": result,
        "score": score_for(result),
        "termination": termination,
        "plies": len(clocks),
        "my_clock_end": my_clock,
        "opp_clock_end": opp_clock,
        "eco": tags.get("ECO"),
        "opening_slug": eco_url.rsplit("/", 1)[-1] if eco_url else None,
        "opening_name": None,
        "first_moves": " ".join(pgn_moves(pgn)),
    }


def lichess_game(g: dict, user: str) -> dict | None:
    if not g.get("rated") or g.get("variant") != "standard" or g.get("status") in SKIP_LICHESS:
        return None
    uid = user.lower()
    color = "white" if g["players"]["white"].get("user", {}).get("id") == uid else "black"
    me, opp = g["players"][color], g["players"]["black" if color == "white" else "white"]
    if "rating" not in me or "rating" not in opp:
        return None
    winner = g.get("winner")
    if winner is None:
        result, termination = "draw", "draw"
    else:
        result = "win" if winner == color else "loss"
        termination = LICHESS_STATUS.get(g["status"], "other")
        if termination == "draw":  # a decisive result can't end in a draw status
            termination = "other"
    clocks = [c / 100 for c in g.get("clocks", [])]
    my_clock, opp_clock = end_clocks(clocks, color)
    moves = g.get("moves", "").split()
    clock = g.get("clock") or {}
    opening = g.get("opening") or {}
    return {
        "site": "lichess",
        "game_id": g["id"],
        "start_utc": datetime.fromtimestamp(g["createdAt"] / 1000, tz=timezone.utc),
        "end_utc": datetime.fromtimestamp(g["lastMoveAt"] / 1000, tz=timezone.utc),
        "time_class": {"ultraBullet": "bullet"}.get(g["perf"], g["perf"]),
        "base_s": clock.get("initial"),
        "inc_s": clock.get("increment"),
        "color": color,
        "my_rating_post": me["rating"] + me.get("ratingDiff", 0),
        "opp_rating_post": opp["rating"] + opp.get("ratingDiff", 0),
        "my_rating": me["rating"],
        "opp_rating": opp["rating"],
        "rating_change": me.get("ratingDiff"),
        "result": result,
        "score": score_for(result),
        "termination": termination,
        "plies": len(moves),
        "my_clock_end": my_clock,
        "opp_clock_end": opp_clock,
        "eco": opening.get("eco"),
        "opening_slug": None,
        "opening_name": opening.get("name"),
        "first_moves": " ".join(moves[:2]),
    }


def expected_score(my_rating: float, opp_rating: float) -> float:
    """The Elo expectation: the share of points a player should score at this rating gap."""
    return 1 / (1 + 10 ** ((opp_rating - my_rating) / 400))


def opening_family(name: str | None) -> str | None:
    """'Sicilian Defense: Najdorf Variation' -> 'Sicilian Defense'."""
    if not isinstance(name, str) or not name:
        return None
    return name.split(":", 1)[0].split(",", 1)[0].strip()


_SLUG_STOP = re.compile(r"\.\.\.|\d+\.")


def family_from_slug(slug: str | None) -> str | None:
    """Chess.com opening slug -> a family name, used only when the ECO code is unknown on Lichess.

    'Sicilian-Defense-Najdorf-Variation-6.Be3' -> 'Sicilian Defense'
    """
    if not isinstance(slug, str) or not slug:
        return None
    words = _SLUG_STOP.split(slug, 1)[0].strip("-").split("-")
    for i, w in enumerate(words):
        if w in {"Defense", "Opening", "Game", "Gambit", "Attack", "System", "Countergambit"}:
            return " ".join(words[: i + 1])
    return " ".join(words[:3]) or None
