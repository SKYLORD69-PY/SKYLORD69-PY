#!/usr/bin/env python3
"""
spotify_now_playing.py
------------------------
Renders a themed "now playing" card as a static SVG, refreshed on a
short cron. This is a snapshot updated every few minutes, not a truly
live socket, because GitHub Actions' scheduler is best-effort and its
documented floor is 5-minute granularity (and busy periods can delay
runs further) -- that's a GitHub Actions constraint, not something a
smarter script can get around.

Behaviour on the "nothing to show" cases is deliberately quiet:
  - Not playing anything right now      -> fall back to "last played"
  - Refresh token missing/revoked        -> exit 1 (loud; this needs
                                             a human to re-auth)
  - Any other transient API hiccup       -> exit 0 without touching
                                             the SVG, so the last good
                                             card just stays up instead
                                             of being replaced by an
                                             error card.
"""

import base64
import os
import sys
import json
import urllib.request
import urllib.error

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_ROOT = "https://api.spotify.com/v1"

BG = "#0A0E14"
CYAN = "#00E5FF"
GREEN = "#00FF66"
DIM = "#5C6773"

WIDTH, HEIGHT = 420, 110


def refresh_access_token(client_id, client_secret, refresh_token):
    import urllib.parse

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode(
        {"grant_type": "refresh_token", "refresh_token": refresh_token}
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())["access_token"]


def api_get(path, access_token):
    req = urllib.request.Request(
        f"{API_ROOT}{path}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 204:
                return None
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 204:
            return None
        raise


def fetch_now_playing(access_token):
    """Returns (track_dict, is_currently_playing: bool) or (None, False)."""
    current = api_get("/me/player/currently-playing", access_token)
    if current and current.get("item"):
        return current, bool(current.get("is_playing"))

    recent = api_get("/me/player/recently-played?limit=1", access_token)
    if recent and recent.get("items"):
        item = recent["items"][0]
        return {"item": item["track"], "progress_ms": None}, False

    return None, False


def fetch_album_art_b64(url):
    """Best-effort. A failure here should never take down the whole card."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "spotify-card-bot"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read()
        mime = resp.headers.get_content_type() or "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(raw).decode()}"
    except Exception:  # noqa: BLE001
        return None


def esc(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def equalizer_bars(is_playing, x, y):
    bars = []
    heights = [14, 22, 10, 18]
    for i, h0 in enumerate(heights):
        bx = x + i * 7
        if is_playing:
            bars.append(
                f'<rect x="{bx}" y="{y + (22 - h0)}" width="4" height="{h0}" rx="2" fill="{GREEN}">'
                f'<animate attributeName="height" values="{h0};6;{h0 + 6};{h0}" '
                f'dur="{0.6 + i * 0.15}s" repeatCount="indefinite"/>'
                f'<animate attributeName="y" values="{y + (22 - h0)};{y + 16};'
                f'{y + (22 - h0 - 6)};{y + (22 - h0)}" dur="{0.6 + i * 0.15}s" repeatCount="indefinite"/>'
                "</rect>"
            )
        else:
            bars.append(f'<rect x="{bx}" y="{y + 10}" width="4" height="6" rx="2" fill="{DIM}"/>')
    return "".join(bars)


def render_svg(track, is_playing, art_b64):
    name = esc(track["name"])
    artists = esc(", ".join(a["name"] for a in track.get("artists", [])) or "Unknown Artist")
    if len(name) > 28:
        name = name[:27] + "\u2026"
    if len(artists) > 40:
        artists = artists[:39] + "\u2026"

    status_text = "NOW PLAYING" if is_playing else "LAST PLAYED"
    status_color = GREEN if is_playing else DIM

    art_x, art_y, art_size = 14, 14, 82
    art_defs = ""
    if art_b64:
        art_defs = (
            f'<clipPath id="artclip"><rect x="{art_x}" y="{art_y}" width="{art_size}" '
            f'height="{art_size}" rx="8"/></clipPath>'
        )
        art_el = (
            f'<image href="{art_b64}" x="{art_x}" y="{art_y}" width="{art_size}" '
            f'height="{art_size}" clip-path="url(#artclip)" preserveAspectRatio="xMidYMid slice"/>'
        )
    else:
        art_el = (
            f'<rect x="{art_x}" y="{art_y}" width="{art_size}" height="{art_size}" rx="8" '
            f'fill="none" stroke="{CYAN}" stroke-opacity="0.4"/>'
            f'<text x="{art_x + art_size / 2}" y="{art_y + art_size / 2 + 5}" '
            f'text-anchor="middle" font-size="26" fill="{CYAN}">\u266a</text>'
        )

    text_x = art_x + art_size + 18
    dot = (
        f'<circle cx="{text_x}" cy="20" r="3.5" fill="{status_color}">'
        + (
            f'<animate attributeName="opacity" values="1;0.25;1" dur="1.4s" repeatCount="indefinite"/>'
            if is_playing
            else ""
        )
        + "</circle>"
    )

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'width="{WIDTH}" height="{HEIGHT}">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" rx="12" fill="{BG}" '
        f'stroke="{CYAN}" stroke-opacity="0.25"/>',
        f"<defs>{art_defs}</defs>" if art_defs else "",
        art_el,
        dot,
        f'<text x="{text_x + 10}" y="24" font-family="monospace" font-size="11" '
        f'letter-spacing="1.5" fill="{status_color}">{status_text}</text>',
        f'<text x="{text_x}" y="52" font-family="monospace" font-size="15" '
        f'font-weight="bold" fill="#F0F6FC">{name}</text>',
        f'<text x="{text_x}" y="72" font-family="monospace" font-size="12" '
        f'fill="{CYAN}">{artists}</text>',
        equalizer_bars(is_playing, text_x, 82),
        "</svg>",
    ]
    return "\n".join(p for p in parts if p)


def main():
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    refresh_token = os.environ.get("SPOTIFY_REFRESH_TOKEN")
    out_path = os.environ.get("OUT_PATH", "assets/spotify.svg")

    if not all([client_id, client_secret, refresh_token]):
        print("::error::Missing one of SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET / "
              "SPOTIFY_REFRESH_TOKEN. See SETUP.md.", file=sys.stderr)
        sys.exit(1)

    try:
        access_token = refresh_access_token(client_id, client_secret, refresh_token)
    except urllib.error.HTTPError as e:
        # A dead/revoked refresh token needs a human to re-run the OAuth flow.
        # That's worth a loud failure, not a silent no-op.
        print(f"::error::Spotify token refresh failed (HTTP {e.code}). The refresh "
              f"token may have been revoked; redo the one-time OAuth step in SETUP.md.",
              file=sys.stderr)
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"::error::Unexpected error refreshing Spotify token: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        track_wrapper, is_playing = fetch_now_playing(access_token)
    except Exception as e:  # noqa: BLE001
        # Transient Spotify hiccup: log it, keep the last good card, exit clean.
        print(f"::warning::Spotify player lookup failed, leaving previous card in place: {e}")
        sys.exit(0)

    if track_wrapper is None or not track_wrapper.get("item"):
        print("Nothing playing and no recent-play history available; leaving previous card in place.")
        sys.exit(0)

    track = track_wrapper["item"]
    art_b64 = None
    images = track.get("album", {}).get("images", [])
    if images:
        smallest = min(images, key=lambda im: im.get("width", 9999))
        art_b64 = fetch_album_art_b64(smallest["url"])

    svg = render_svg(track, is_playing, art_b64)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg)

    print(f"Wrote now-playing card for '{track['name']}' (playing={is_playing}) -> {out_path}")


if __name__ == "__main__":
    main()
