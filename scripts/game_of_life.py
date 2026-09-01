#!/usr/bin/env python3
"""
game_of_life.py
-----------------
Turns the GitHub contribution calendar into the initial state of
Conway's Game of Life, simulates it, and renders the result as a
single self-looping animated SVG (pure SMIL, no JS — GitHub strips
<script> tags from README images anyway).

Why a Personal Access Token and not the default GITHUB_TOKEN:
  contributionsCollection is only exposed over the GraphQL API, and
  GraphQL always requires a token with `read:user` — the default
  Actions token isn't scoped for it. This is the one workflow in the
  whole repo that needs a dedicated secret (GH_PAT).

Why the grid wraps top/bottom and left/right (a torus):
  The real calendar is only 7 rows tall. On a flat grid that's not
  enough room for Game of Life patterns to do anything interesting
  before hitting a wall and dying. Wrapping both axes keeps the
  simulation alive and visually busy for the full animation.
"""

import os
import sys
import json
import urllib.request
import urllib.error

GRAPHQL_URL = "https://api.github.com/graphql"
GENERATIONS = 24
FRAME_SECONDS = 0.45
CELL = 11
GAP = 3

BG = "#0A0E14"
ALIVE_FILL = "#00FF66"  # matrix green
GLOW = "#00E5FF"        # neon cyan


QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks {
          contributionDays {
            contributionCount
            weekday
          }
        }
      }
    }
  }
}
"""


def fetch_calendar(username, token):
    body = json.dumps({"query": QUERY, "variables": {"login": username}}).encode()
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "SKYLORD69-PY-profile-bot",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode())
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    weeks = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    # grid[row][col] ; row = weekday (0=Sun..6=Sat), col = week index
    cols = len(weeks)
    grid = [[0] * cols for _ in range(7)]
    for col, week in enumerate(weeks):
        for day in week["contributionDays"]:
            grid[day["weekday"]][col] = 1 if day["contributionCount"] > 0 else 0
    return grid


def step(grid):
    """One Conway's Game of Life generation on a toroidal grid."""
    rows, cols = len(grid), len(grid[0])
    new = [[0] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            n = 0
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    n += grid[(r + dr) % rows][(c + dc) % cols]
            alive = grid[r][c]
            new[r][c] = 1 if (n == 3 or (alive and n == 2)) else 0
    return new


def simulate(seed, generations):
    frames = [seed]
    current = seed
    for _ in range(generations - 1):
        current = step(current)
        frames.append(current)
    return frames


def render_svg(frames):
    rows, cols = len(frames[0]), len(frames[0][0])
    width = cols * (CELL + GAP) + GAP
    height = rows * (CELL + GAP) + GAP + 24  # +24 for footer caption
    n = len(frames)
    total_dur = round(n * FRAME_SECONDS, 3)

    key_times = ";".join(f"{i / n:.5f}" for i in range(n + 1))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}">',
        "<defs>",
        '<filter id="glow" x="-60%" y="-60%" width="220%" height="220%">',
        '<feGaussianBlur stdDeviation="1.4" result="blur"/>',
        '<feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>',
        "</filter>",
        f"<style>.c{{fill:{ALIVE_FILL};filter:url(#glow)}}</style>",
        "</defs>",
        f'<rect width="{width}" height="{height}" fill="{BG}" rx="10"/>',
    ]

    for gi, frame in enumerate(frames):
        values = ";".join("1" if k == gi else "0" for k in range(n + 1))
        cells = []
        for r in range(rows):
            for c in range(cols):
                if frame[r][c]:
                    x = GAP + c * (CELL + GAP)
                    y = GAP + r * (CELL + GAP)
                    cells.append(
                        f'<rect class="c" x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2"/>'
                    )
        parts.append(f'<g opacity="0">')
        parts.append(
            f'<animate attributeName="opacity" dur="{total_dur}s" '
            f'keyTimes="{key_times}" values="{values}" calcMode="discrete" '
            f'repeatCount="indefinite"/>'
        )
        parts.extend(cells)
        parts.append("</g>")

    caption_y = height - 8
    parts.append(
        f'<text x="{width / 2:.0f}" y="{caption_y}" text-anchor="middle" '
        f'font-family="monospace" font-size="10" fill="{GLOW}" opacity="0.85">'
        f"gen {n} \u00b7 conway&#x27;s game of life, seeded from real contributions</text>"
    )
    parts.append("</svg>")
    return "\n".join(parts)


def main():
    token = os.environ.get("GH_PAT")
    username = os.environ.get("TARGET_USER", "SKYLORD69-PY")
    out_path = os.environ.get("OUT_PATH", "assets/game-of-life.svg")

    if not token:
        print(
            "::error::GH_PAT is not set. This feature needs a classic PAT with the "
            "'read:user' scope, since GraphQL contribution data isn't reachable with "
            "the default GITHUB_TOKEN. See SETUP.md.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        seed = fetch_calendar(username, token)
    except urllib.error.HTTPError as e:
        print(f"::error::GitHub GraphQL API returned HTTP {e.code}: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"::error::Failed to fetch or parse contribution calendar: {e}", file=sys.stderr)
        sys.exit(1)

    total_alive = sum(sum(row) for row in seed)
    if total_alive == 0:
        print("::warning::No contributions found in the last year; simulating an empty board.")

    frames = simulate(seed, GENERATIONS)
    svg = render_svg(frames)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg)

    print(f"Rendered {GENERATIONS} generations from {total_alive} live seed cell(s) -> {out_path}")


if __name__ == "__main__":
    main()
