"""Download every rated game from my Chess.com and Lichess accounts into data/raw/.

    python scripts/fetch.py            # incremental: only what's new since the last run
    python scripts/fetch.py --full     # start over

Raw files are not committed (they include opponents' usernames). build.py turns them into
data/games.parquet, which keeps only what the analysis needs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
ACCOUNTS = json.loads((ROOT / "accounts.json").read_text())
HEADERS = {"User-Agent": "chess-analytics-script/1.0"}


def get(url: str, accept: str = "application/json", tries: int = 5):
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={**HEADERS, "Accept": accept})
        try:
            return urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as err:
            if err.code == 429 or err.code >= 500:
                wait = 60 * (attempt + 1)
                print(f"  {err.code}, waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError:
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"gave up on {url}")


def chesscom(full: bool) -> None:
    user = ACCOUNTS["chesscom"].lower()
    out = RAW / "chesscom"
    out.mkdir(parents=True, exist_ok=True)
    archives = json.load(get(f"https://api.chess.com/pub/player/{user}/games/archives"))["archives"]
    for i, url in enumerate(archives):
        name = out / (url.rsplit("/", 2)[-2] + "-" + url.rsplit("/", 1)[-1] + ".json")
        # Past months never change, so only the last two are refetched on incremental runs.
        if name.exists() and not full and i < len(archives) - 2:
            continue
        name.write_bytes(get(url).read())
        print(f"chess.com {name.stem}", end="\r")
        time.sleep(0.3)
    print(f"chess.com: {len(archives)} months")


def lichess(full: bool) -> None:
    out = RAW / "lichess.ndjson"
    out.parent.mkdir(parents=True, exist_ok=True)
    since = 0
    if out.exists() and not full:
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                since = max(since, json.loads(line)["createdAt"])
    elif out.exists():
        out.unlink()

    params = (
        "rated=true&perfType=ultraBullet,bullet,blitz,rapid,classical&moves=true&clocks=true"
        "&opening=true&evals=false&sort=dateAsc"
    )
    count = 0
    # The export stream sometimes drops after a few thousand games. Games come oldest
    # first, so each retry resumes from the newest game already saved.
    for attempt in range(20):
        url = f"https://lichess.org/api/games/user/{ACCOUNTS['lichess']}?{params}"
        if since:
            url += f"&since={since + 1}"
        try:
            with get(url, accept="application/x-ndjson") as res, out.open("a", encoding="utf-8") as f:
                for raw in res:
                    line = raw.decode("utf-8").strip()
                    if not line:
                        continue
                    f.write(line + "\n")
                    since = max(since, json.loads(line)["createdAt"])
                    count += 1
                    if count % 200 == 0:
                        print(f"lichess {count} games", end="\r")
            break
        except Exception as err:  # noqa: BLE001 - any drop means "resume"
            print(f"\nlichess stream dropped after {count} games ({err!r}); resuming", file=sys.stderr)
            time.sleep(5)
    print(f"lichess: {count} new games")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--only", choices=["chesscom", "lichess"])
    args = ap.parse_args()
    if args.only != "lichess":
        chesscom(args.full)
    if args.only != "chesscom":
        lichess(args.full)
