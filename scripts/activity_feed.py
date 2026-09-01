#!/usr/bin/env python3
"""
activity_feed.py
-------------------
Pulls three optional streams into one "recent activity" block:
  1. Recent GitHub events (pushes, new repos, PRs opened)
  2. Recent releases published across your repos
  3. Recent blog posts, IF you set a BLOG_RSS_URL repo variable

(3) is opt-in on purpose: not fetching for a blog you don't have is a
design decision made once here, not a question you need to answer
before this repo is usable. Leave BLOG_RSS_URL unset and that section
simply doesn't render.
"""

import os
import sys
import re
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone

API_ROOT = "https://api.github.com"
START_MARK = "<!--ACTIVITY:START-->"
END_MARK = "<!--ACTIVITY:END-->"
MAX_ITEMS = 5

EVENT_ICONS = {
    "PushEvent": "\U0001F4E6",       # package
    "ReleaseEvent": "\U0001F680",    # rocket
    "PullRequestEvent": "\U0001F500",  # twisted arrows
    "CreateEvent": "\u2728",         # sparkles
    "IssuesEvent": "\U0001F4DD",     # memo
}


def gh_get(path, token):
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


def humanize(event):
    kind = event["type"]
    repo = event["repo"]["name"]
    icon = EVENT_ICONS.get(kind, "\u25CF")
    if kind == "PushEvent":
        n = len(event.get("payload", {}).get("commits", []))
        label = f"pushed {n} commit{'s' if n != 1 else ''} to"
    elif kind == "ReleaseEvent":
        tag = event.get("payload", {}).get("release", {}).get("tag_name", "")
        label = f"published release {tag} on".strip()
    elif kind == "PullRequestEvent":
        action = event.get("payload", {}).get("action", "updated")
        label = f"{action} a pull request on"
    elif kind == "CreateEvent" and event.get("payload", {}).get("ref_type") == "repository":
        label = "created"
    elif kind == "IssuesEvent":
        action = event.get("payload", {}).get("action", "updated")
        label = f"{action} an issue on"
    else:
        return None
    return f"{icon} {label} [`{repo}`](https://github.com/{repo})"


def fetch_recent_activity(username, token):
    events = gh_get(f"/users/{username}/events/public?per_page=30", token)
    lines, seen = [], set()
    for e in events:
        line = humanize(e)
        if line and line not in seen:
            lines.append(line)
            seen.add(line)
        if len(lines) >= MAX_ITEMS:
            break
    return lines


def fetch_blog_posts(rss_url, limit=3):
    try:
        import feedparser  # provided via requirements.txt
    except ImportError:
        print("::warning::feedparser not installed but BLOG_RSS_URL is set; skipping blog section.")
        return []
    try:
        parsed = feedparser.parse(rss_url)
        posts = []
        for entry in parsed.entries[:limit]:
            title = entry.get("title", "Untitled post")
            link = entry.get("link", rss_url)
            posts.append(f"\U0001F4DD [{title}]({link})")
        return posts
    except Exception as e:  # noqa: BLE001
        print(f"::warning::Failed to read blog RSS feed, skipping this run's blog section: {e}")
        return []


def render_block(activity_lines, blog_lines):
    parts = [START_MARK]
    if activity_lines:
        parts.append("**Recent activity**")
        parts.extend(f"- {line}" for line in activity_lines)
    else:
        parts.append("_No recent public activity to show yet._")
    if blog_lines:
        parts.append("")
        parts.append("**Latest posts**")
        parts.extend(f"- {line}" for line in blog_lines)
    parts.append(END_MARK)
    return "\n".join(parts)


def inject(readme_path, block):
    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()
    pattern = re.compile(re.escape(START_MARK) + r".*?" + re.escape(END_MARK), re.DOTALL)
    if not pattern.search(content):
        print(f"::error::Markers {START_MARK} / {END_MARK} not found in {readme_path}")
        sys.exit(1)
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(pattern.sub(block, content))


def main():
    token = os.environ.get("GITHUB_TOKEN")
    username = os.environ.get("TARGET_USER", "SKYLORD69-PY")
    readme_path = os.environ.get("README_PATH", "README.md")
    blog_rss_url = os.environ.get("BLOG_RSS_URL", "").strip()

    if not token:
        print("::error::GITHUB_TOKEN is not set.", file=sys.stderr)
        sys.exit(1)

    try:
        activity_lines = fetch_recent_activity(username, token)
    except urllib.error.HTTPError as e:
        print(f"::error::GitHub API returned HTTP {e.code}: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"::error::Unexpected failure fetching activity: {e}", file=sys.stderr)
        sys.exit(1)

    blog_lines = fetch_blog_posts(blog_rss_url) if blog_rss_url else []

    block = render_block(activity_lines, blog_lines)
    inject(readme_path, block)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"Injected {len(activity_lines)} activity item(s) and {len(blog_lines)} "
          f"blog item(s) into {readme_path} at {stamp}.")


if __name__ == "__main__":
    main()
