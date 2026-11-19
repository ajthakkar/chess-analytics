"""Local time and playing sessions."""

from __future__ import annotations

import pandas as pd

# I lived near Chicago until moving to Columbus for college in August 2026.
MOVE_DATE = pd.Timestamp("2026-08-15", tz="UTC")
SESSION_GAP_MIN = 30


def to_local(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    start = pd.to_datetime(df.start_utc, utc=True)
    central = start.dt.tz_convert("America/Chicago").dt.tz_localize(None)
    eastern = start.dt.tz_convert("America/New_York").dt.tz_localize(None)
    df["start_local"] = central.where(start < MOVE_DATE, eastern)
    df["hour"] = df.start_local.dt.hour
    df["weekday"] = df.start_local.dt.day_of_week
    df["year"] = df.start_local.dt.year
    return df


def add_sessions(df: pd.DataFrame, gap_min: float = SESSION_GAP_MIN) -> pd.DataFrame:
    """A session is a run of games, on either site, with no break longer than gap_min minutes
    between one game ending and the next starting."""
    df = df.sort_values("start_utc").reset_index(drop=True).copy()
    start = pd.to_datetime(df.start_utc, utc=True)
    end = pd.to_datetime(df.end_utc, utc=True)
    prev_end = end.shift(1)
    gap = (start - prev_end).dt.total_seconds() / 60
    new = gap.isna() | (gap > gap_min)
    df["session_id"] = new.cumsum()
    df["game_in_session"] = df.groupby("session_id").cumcount() + 1
    df["session_games"] = df.groupby("session_id").session_id.transform("size")
    df["minutes_since_prev"] = gap.where(~new)
    df["prev_result"] = df.groupby("session_id").result.shift(1)
    df["is_last_in_session"] = df.game_in_session == df.session_games

    # Losses in a row right before this game, within the session.
    streak = []
    run = 0
    last_session = None
    for sid, res in zip(df.session_id, df.result.shift(1)):
        if sid != last_session:
            run = 0
            last_session = sid
            streak.append(0)
            continue
        run = run + 1 if res == "loss" else 0
        streak.append(run)
    df["loss_streak_before"] = streak
    return df
