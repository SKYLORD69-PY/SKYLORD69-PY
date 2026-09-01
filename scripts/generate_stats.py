#!/usr/bin/env python3
"""
generate_stats.py
--------------------
A from-scratch, themed replacement for embedding
github-readme-stats.vercel.app directly. The public instance is
shared by hundreds of thousands of profiles and is well documented
(by its own maintainers) to intermittently 503/rate-limit -- exactly
the kind of "silently broken README" this whole project is trying to
avoid. Generating our own two cards, on our own schedule, on our own
GitHub Actions minutes, means the only thing that has to be up is
GitHub itself.

Trade-off, stated plainly: "top languages" here is repo-count based
(one vote per repo, using each repo's primary language), not
byte-weighted like the original tool. Byte-weighted requires one API
call per repo, which doesn't scale politely for the free API quota.
Repo-count is an honest, cheap proxy and is labelled as such in the
card footer.
"""

import os
import sys
import json
import urllib.request
import urllib.error

API_ROOT = "https://api.github.com"
GRAPHQL_URL = f"{API_ROOT}/graphql"

BG = "#0A0E14"
CYAN = "#00E5FF"
GREEN = "#00FF66"
TEXT = "#F0F6FC"
DIM = "#5C6773"

LANG_COLORS = {
    "Python": "#3776AB", "JavaScript": "#F7DF1E", "TypeScript": "#3178C6",
    "C++": "#00599C", "C": "#A8B9CC", "Jupyter Notebook": "#DA5B0B",
    "HTML": "#E34F26", "CSS": "#1572B6", "Shell": "#89E051",
    "Java": "#B07219", "Go": "#00ADD8",
}
FALLBACK_COLOR = "#00E5FF"

STATS_QUERY = """
query($login: String!) {
  user(login: $login) {
    followers { totalCount }
    contributionsCollection { contributionCalendar { totalContributions } }
  }
}
"""


def rest_get(path, token):
    req = urllib.request.Request(
        f"{API_ROOT}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "SKYLORD69-PY-profile-bot",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def graphql(query, variables, token):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode())
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def gather(username, gh_token, gh_pat):
    repos = rest_get(f"/users/{username}/repos?type=owner&per_page=100", gh_token)
    public_repos = [r for r in repos if not r.get("fork")]
    total_stars = sum(r.get("stargazers_count", 0) for r in public_repos)

    lang_counts = {}
    for r in public_repos:
        lang = r.get("language")
        if lang:
            lang_counts[lang] = lang_counts.get(lang, 0) + 1

    followers, total_contributions = 0, 0
    if gh_pat:
        try:
            data = graphql(STATS_QUERY, {"login": username}, gh_pat)
            followers = data["user"]["followers"]["totalCount"]
            total_contributions = data["user"]["contributionsCollection"][
                "contributionCalendar"
            ]["totalContributions"]
        except Exception as e:  # noqa: BLE001
            print(f"::warning::Follower/contribution lookup failed, continuing without it: {e}")

    return {
        "public_repos": len(public_repos),
        "total_stars": total_stars,
        "followers": followers,
        "total_contributions": total_contributions,
        "languages": sorted(lang_counts.items(), key=lambda kv: -kv[1])[:6],
    }


def card_shell(width, height, body, title):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}">'
        f'<rect width="{width}" height="{height}" rx="12" fill="{BG}" '
        f'stroke="{CYAN}" stroke-opacity="0.25"/>'
        f'<text x="18" y="28" font-family="monospace" font-size="13" '
        f'letter-spacing="1" fill="{CYAN}">{title}</text>'
        f'<line x1="18" y1="38" x2="{width - 18}" y2="38" stroke="{CYAN}" stroke-opacity="0.15"/>'
        f"{body}</svg>"
    )


def render_stats_card(stats):
    rows = [
        ("Public repos", stats["public_repos"]),
        ("Total stars", stats["total_stars"]),
        ("Followers", stats["followers"]),
        ("Contributions (1y)", stats["total_contributions"]),
    ]
    body = ""
    for i, (label, value) in enumerate(rows):
        y = 62 + i * 26
        body += (
            f'<text x="18" y="{y}" font-family="monospace" font-size="13" fill="{DIM}">{label}</text>'
            f'<text x="290" y="{y}" font-family="monospace" font-size="13" font-weight="bold" '
            f'text-anchor="end" fill="{TEXT}">{value:,}</text>'
        )
    return card_shell(320, 62 + len(rows) * 26 + 14, body, "GH_STATS --user SKYLORD69-PY")


def render_langs_card(languages):
    if not languages:
        body = (
            f'<text x="18" y="62" font-family="monospace" font-size="12" fill="{DIM}">'
            "no public repos with a detected language yet</text>"
        )
        return card_shell(320, 90, body, "TOP_LANGUAGES --by repo-count")

    total = sum(c for _, c in languages) or 1
    body = ""
    bar_x, bar_w = 18, 284
    y = 54
    for lang, count in languages:
        pct = count / total
        color = LANG_COLORS.get(lang, FALLBACK_COLOR)
        seg_w = max(3, bar_w * pct)
        body += f'<rect x="{bar_x:.1f}" y="{y - 10}" width="{seg_w:.1f}" height="10" rx="4" fill="{color}"/>'
        bar_x += seg_w + 3
    y2 = y + 24
    for i, (lang, count) in enumerate(languages):
        pct = 100 * count / total
        color = LANG_COLORS.get(lang, FALLBACK_COLOR)
        col = i % 2
        row = i // 2
        lx = 18 + col * 160
        ly = y2 + row * 22
        body += (
            f'<circle cx="{lx + 4}" cy="{ly - 4}" r="4" fill="{color}"/>'
            f'<text x="{lx + 14}" y="{ly}" font-family="monospace" font-size="11" fill="{TEXT}">'
            f"{lang} {pct:.0f}%</text>"
        )
    rows_used = (len(languages) + 1) // 2
    height = y2 + rows_used * 22 + 6
    return card_shell(320, height, body, "TOP_LANGUAGES --by repo-count")


def main():
    gh_token = os.environ.get("GITHUB_TOKEN")
    gh_pat = os.environ.get("GH_PAT")  # optional; enables followers + contributions
    username = os.environ.get("TARGET_USER", "SKYLORD69-PY")
    stats_out = os.environ.get("STATS_OUT", "assets/stats.svg")
    langs_out = os.environ.get("LANGS_OUT", "assets/top-langs.svg")

    if not gh_token:
        print("::error::GITHUB_TOKEN is not set.", file=sys.stderr)
        sys.exit(1)

    try:
        stats = gather(username, gh_token, gh_pat)
    except urllib.error.HTTPError as e:
        print(f"::error::GitHub API returned HTTP {e.code}: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"::error::Unexpected failure gathering stats: {e}", file=sys.stderr)
        sys.exit(1)

    for path, svg in (
        (stats_out, render_stats_card(stats)),
        (langs_out, render_langs_card(stats["languages"])),
    ):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)

    print(f"Stats card + top-langs card written for {username}: {stats}")


if __name__ == "__main__":
    main()
