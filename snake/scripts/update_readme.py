#!/usr/bin/env python3
"""
Setlist updater.

Pulls the N most recently active public, non-fork repos for GH_USERNAME
and rewrites the table between <!-- REPOS_START --> and <!-- REPOS_END -->
in README.md. Triggered daily (and on demand) by
.github/workflows/update-readme.yml.
"""

import os
import re
import sys

import requests

USERNAME = os.environ.get("GH_USERNAME", "SKYLORD69-PY")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
MAX_REPOS = 5
COMMIT_MSG_MAX_LEN = 60
README_PATH = "README.md"
START_MARKER = "<!-- REPOS_START -->"
END_MARKER = "<!-- REPOS_END -->"

API_ROOT = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def fetch_repos():
    """Fetch the most recently pushed-to repos, skipping forks and the profile repo itself."""
    resp = requests.get(
        f"{API_ROOT}/users/{USERNAME}/repos",
        headers=HEADERS,
        params={"sort": "pushed", "direction": "desc", "per_page": 30, "type": "owner"},
        timeout=20,
    )
    resp.raise_for_status()
    repos = resp.json()
    repos = [r for r in repos if not r.get("fork") and r["name"].lower() != USERNAME.lower()]
    return repos[:MAX_REPOS]


def latest_commit_message(repo_name):
    """Grab the first line of the most recent commit message on the default branch."""
    resp = requests.get(
        f"{API_ROOT}/repos/{USERNAME}/{repo_name}/commits",
        headers=HEADERS,
        params={"per_page": 1},
        timeout=20,
    )
    if resp.status_code != 200 or not resp.json():
        return "—"
    msg = resp.json()[0]["commit"]["message"].split("\n")[0].strip()
    if len(msg) > COMMIT_MSG_MAX_LEN:
        msg = msg[: COMMIT_MSG_MAX_LEN - 1] + "…"
    return msg


def escape_cell(text):
    """Table cells can't contain a raw pipe without breaking the row."""
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def build_table(repos):
    rows = [
        "| Track / Repo | Last Riff (Commit) | Signal Details (Description) |",
        "|---|---|---|",
    ]
    if not repos:
        rows.append("| _No public tracks yet — first release pending._ | — | — |")
        return "\n".join(rows)

    for repo in repos:
        name = escape_cell(repo["name"])
        link = repo["html_url"]
        description = escape_cell(repo.get("description") or "No liner notes yet.")
        commit_msg = escape_cell(latest_commit_message(repo["name"]))
        rows.append(f"| **[{name}]({link})** | `{commit_msg}` | {description} |")

    return "\n".join(rows)


def update_readme(table_md):
    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL)
    if not pattern.search(content):
        print(f"Markers {START_MARKER} / {END_MARKER} not found in {README_PATH}.", file=sys.stderr)
        sys.exit(1)

    replacement = f"{START_MARKER}\n{table_md}\n{END_MARKER}"
    new_content = pattern.sub(replacement, content)

    if new_content == content:
        print("Setlist already current — no changes.")
        return

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"Setlist updated with {table_md.count(chr(10)) - 1} track(s).")


def main():
    repos = fetch_repos()
    table_md = build_table(repos)
    update_readme(table_md)


if __name__ == "__main__":
    main()
