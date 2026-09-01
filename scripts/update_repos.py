#!/usr/bin/env python3
"""
update_repos.py
----------------
The ONE feature carried over from the old profile: a live table of the
repos SKYLORD69-PY is actively working on right now, sorted by most
recently pushed. Rewritten from scratch against the current GitHub
REST API (no old code reused).

Design goals:
  - Zero extra secrets. Uses the default GITHUB_TOKEN that every
    Actions run already has.
  - Fails LOUD on real errors (bad token, API down) so GitHub's
    "workflow run failed" email actually reaches you.
  - Fails QUIET on "nothing to show yet" (brand-new account, API
    briefly empty) by writing a graceful placeholder instead of
    crashing the whole pipeline.
  - Idempotent: always writes the freshest version of the block.
    git-auto-commit-action only creates a commit if the file content
    actually changed, so this can run every few hours without
    spamming your commit history.
"""

import os
import sys
import re
import urllib.request
import urllib.error
import json

API_ROOT = "https://api.github.com"
START_MARK = "<!--REPO-LIST:START-->"
END_MARK = "<!--REPO-LIST:END-->"
MAX_REPOS = 5

# Repos that are infrastructure, not "current work", so they never
# clutter their own showcase.
IGNORE_REPOS = {"SKYLORD69-PY"}


def gh_request(path, token):
    req = urllib.request.Request(
        f"{API_ROOT}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {token}",
            "User-Agent": "SKYLORD69-PY-profile-bot",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def fetch_active_repos(username, token):
    repos = gh_request(
        f"/users/{username}/repos?type=owner&sort=pushed&direction=desc&per_page=100",
        token,
    )
    active = [
        r
        for r in repos
        if not r.get("fork")
        and not r.get("archived")
        and r.get("name") not in IGNORE_REPOS
    ]
    return active[:MAX_REPOS]


LANG_COLORS = {
    "Python": "3776AB",
    "JavaScript": "F7DF1E",
    "TypeScript": "3178C6",
    "C++": "00599C",
    "C": "A8B9CC",
    "Jupyter Notebook": "DA5B0B",
    "HTML": "E34F26",
    "CSS": "1572B6",
    "Shell": "89E051",
}


def render_row(repo):
    name = repo["name"]
    url = repo["html_url"]
    desc = (repo.get("description") or "Work in progress \u2014 no description yet.").strip()
    if len(desc) > 72:
        desc = desc[:69].rstrip() + "..."
    lang = repo.get("language") or "Misc"
    stars = repo.get("stargazers_count", 0)
    color = LANG_COLORS.get(lang, "00E5FF")
    lang_badge = (
        f"![{lang}](https://img.shields.io/badge/{lang.replace(' ', '%20')}-{color}"
        f"?style=flat-square&logo=github&logoColor=white)"
    )
    star_str = f"\u2b50 {stars}" if stars else ""
    return f"| **[{name}]({url})** | {desc} | {lang_badge} | {star_str} |"


def render_block(repos, username):
    if not repos:
        return (
            f"{START_MARK}\n"
            f"> _No public activity yet \u2014 [SKYLORD69-PY](https://github.com/{username}) "
            f"is between quests. Check back soon._\n"
            f"{END_MARK}"
        )
    header = (
        "| Repository | What it is | Stack | |\n"
        "|:--|:--|:--|:--:|\n"
    )
    rows = "\n".join(render_row(r) for r in repos)
    return f"{START_MARK}\n{header}{rows}\n{END_MARK}"


def inject(readme_path, block):
    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()
    pattern = re.compile(
        re.escape(START_MARK) + r".*?" + re.escape(END_MARK), re.DOTALL
    )
    if not pattern.search(content):
        print(f"::error::Markers {START_MARK} / {END_MARK} not found in {readme_path}")
        sys.exit(1)
    new_content = pattern.sub(block, content)
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(new_content)


def main():
    token = os.environ.get("GITHUB_TOKEN")
    username = os.environ.get("TARGET_USER", "SKYLORD69-PY")
    readme_path = os.environ.get("README_PATH", "README.md")

    if not token:
        print("::error::GITHUB_TOKEN is not set.", file=sys.stderr)
        sys.exit(1)

    try:
        repos = fetch_active_repos(username, token)
    except urllib.error.HTTPError as e:
        print(f"::error::GitHub API returned HTTP {e.code}: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:  # noqa: BLE001 - top-level safety net for a scheduled job
        print(f"::error::Unexpected failure fetching repos: {e}", file=sys.stderr)
        sys.exit(1)

    block = render_block(repos, username)
    inject(readme_path, block)
    print(f"Injected {len(repos)} active repo(s) into {readme_path}.")


if __name__ == "__main__":
    main()
