#!/usr/bin/env python3
"""
update_repos.py
================
Fetches SKYLORD69-PY's top public, non-forked GitHub repositories and
injects a formatted Markdown table into README.md, between the
<!-- REPOS_START --> / <!-- REPOS_END --> marker comments.

Usage:
    python scripts/update_repos.py

Runs automatically every 12 hours (and on every push to main) via
.github/workflows/update-readme.yml — no manual steps required.
"""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

GITHUB_USERNAME = "SKYLORD69-PY"
REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"
API_URL = f"https://api.github.com/users/{GITHUB_USERNAME}/repos"

MAX_REPOS = 6
MAX_DESCRIPTION_LEN = 90
START_MARKER = "<!-- REPOS_START -->"
END_MARKER = "<!-- REPOS_END -->"
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5

# A GITHUB_TOKEN raises the API rate limit from 60 to 5,000 requests/hour.
# GitHub Actions injects this automatically -- no manual secret setup needed.
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

LANGUAGE_ICONS = {
    "Python": "🐍",
    "Jupyter Notebook": "📓",
    "JavaScript": "📜",
    "TypeScript": "🔷",
    "HTML": "🌐",
    "CSS": "🎨",
    "C++": "⚙️",
    "C": "⚙️",
    "Java": "☕",
    "Go": "🐹",
    "Rust": "🦀",
    "Shell": "💻",
}


def request_with_retry(
    url: str, headers: dict[str, str], params: dict[str, Any]
) -> requests.Response:
    """GET a URL with a few retries, so one transient hiccup doesn't fail the whole run.

    Retries on network errors, rate limiting (403), and 5xx responses. Anything
    else (404, bad credentials, etc.) fails immediately -- retrying won't fix those.
    """
    last_exc: requests.RequestException | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=15)
        except requests.RequestException as exc:
            last_exc = exc
            print(f"⚠️  Network error (attempt {attempt}/{MAX_RETRIES}): {exc}", file=sys.stderr)
        else:
            if response.status_code == 403 and "rate limit" in response.text.lower():
                print(
                    f"⏳ GitHub API rate-limited (attempt {attempt}/{MAX_RETRIES}) — "
                    "set a GITHUB_TOKEN with more quota if this keeps happening.",
                    file=sys.stderr,
                )
            elif response.status_code >= 500:
                print(
                    f"⚠️  GitHub API returned {response.status_code} "
                    f"(attempt {attempt}/{MAX_RETRIES})",
                    file=sys.stderr,
                )
            else:
                response.raise_for_status()
                return response

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    if last_exc:
        raise last_exc
    raise RuntimeError(f"GitHub API request failed after {MAX_RETRIES} attempts: {url}")


def fetch_repos() -> list[dict[str, Any]]:
    """Fetch every repository owned by GITHUB_USERNAME, handling pagination."""
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    repos: list[dict[str, Any]] = []
    page = 1

    while True:
        params = {
            "type": "owner",
            "sort": "pushed",
            "direction": "desc",
            "per_page": 100,
            "page": page,
        }
        response = request_with_retry(API_URL, headers, params)
        batch = response.json()

        if not batch:
            break

        repos.extend(batch)

        if len(batch) < 100:
            break
        page += 1

    return repos


def select_top_repos(
    repos: list[dict[str, Any]], limit: int = MAX_REPOS
) -> list[dict[str, Any]]:
    """Drop forks, archived repos, and the profile repo itself; keep the most recently active."""
    candidates = [
        repo
        for repo in repos
        if not repo.get("fork")
        and not repo.get("archived")
        and repo.get("name", "").lower() != GITHUB_USERNAME.lower()
    ]
    candidates.sort(key=lambda repo: repo.get("pushed_at") or "", reverse=True)
    return candidates[:limit]


def truncate(text: str, limit: int = MAX_DESCRIPTION_LEN) -> str:
    """Keep table rows tidy by capping overly long descriptions."""
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def format_commit_date(iso_timestamp: str | None) -> str:
    """Turn a GitHub ISO-8601 push timestamp into a short, readable date."""
    if not iso_timestamp:
        return "—"
    try:
        return datetime.strptime(iso_timestamp, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d")
    except ValueError:
        return "—"


def format_table(repos: list[dict[str, Any]]) -> str:
    """Render the repo list as a Markdown table matching the README's terminal HUD style."""
    if not repos:
        return (
            "| ⚠️ | No public repositories found (or the GitHub API was rate-limited). |\n"
            "|---|---|\n"
        )

    header = (
        "| Repository | 🕒 Last Commit | 🛠️ Language | Description |\n"
        "|:------------|:--------------:|:------------|:------------|\n"
    )

    rows = []
    for repo in repos:
        name = repo.get("name", "unknown")
        url = repo.get("html_url", "#")
        last_commit = format_commit_date(repo.get("pushed_at"))
        language = repo.get("language") or "—"
        icon = LANGUAGE_ICONS.get(language, "🔹")
        description = repo.get("description") or "_No description provided._"
        description = truncate(description.replace("|", "\\|"))
        rows.append(f"| [**{name}**]({url}) | {last_commit} | {icon} {language} | {description} |")

    return header + "\n".join(rows) + "\n"


def inject_into_readme(table_markdown: str) -> None:
    """Replace everything between the marker comments with the freshly rendered table."""
    if not README_PATH.exists():
        print(f"❌ README not found at {README_PATH}", file=sys.stderr)
        sys.exit(1)

    content = README_PATH.read_text(encoding="utf-8")

    if START_MARKER not in content or END_MARKER not in content:
        print("❌ REPOS_START / REPOS_END markers not found in README.md", file=sys.stderr)
        sys.exit(1)

    pattern = re.compile(
        re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), flags=re.DOTALL
    )
    replacement = f"{START_MARKER}\n{table_markdown}\n{END_MARKER}"
    new_content = pattern.sub(replacement, content)

    if new_content == content:
        print("ℹ️  README.md already up to date — no changes written.")
        return

    README_PATH.write_text(new_content, encoding="utf-8")
    print("✅ README.md updated with fresh repository data.")


def main() -> None:
    print(f"📡 Fetching repositories for {GITHUB_USERNAME}...")
    try:
        repos = fetch_repos()
    except requests.RequestException as exc:
        print(f"❌ GitHub API request failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"🔎 Found {len(repos)} total repositories.")

    top_repos = select_top_repos(repos)
    print(f"🏆 Selected top {len(top_repos)} non-forked repositories by star count.")

    table = format_table(top_repos)
    inject_into_readme(table)


if __name__ == "__main__":
    main()
