#!/usr/bin/env python3
"""
guestbook.py
--------------
Anyone can sign the guestbook by opening an issue from the
"Guestbook Entry" issue form (see .github/ISSUE_TEMPLATE/guestbook.yml).
This script runs when that issue is opened, and:
  1. Reads the issue body GitHub already structured for us
  2. Sanitizes the message (public write access = hostile input by
     default: strip HTML, strip markdown link/image syntax, collapse
     newlines, hard length cap)
  3. Appends a JSON record (source of truth) and regenerates
     GUESTBOOK.md (the human-readable view) from the full JSON list
  4. Reacts to the issue with a heart, then closes + locks it so the
     guestbook stays an append-only wall, not a comment thread

This never touches the profile README directly -- a bad actor
spamming the guestbook should not be able to deface the main page,
only their own dedicated file.
"""

import os
import sys
import json
import re
import urllib.request
import urllib.error

API_ROOT = "https://api.github.com"
MAX_MESSAGE_LEN = 200
GUESTBOOK_JSON = "data/guestbook.json"
GUESTBOOK_MD = "GUESTBOOK.md"
MAX_SHOWN = 40


def sanitize(text):
    text = text or ""
    text = re.sub(r"<[^>]*>", "", text)          # strip HTML tags
    text = text.replace("[", "(").replace("]", ")")  # neutralize md links
    text = re.sub(r"[\r\n]+", " ", text)          # collapse newlines
    text = re.sub(r"\|", "\u2758", text)           # protect table formatting
    text = text.strip()
    if len(text) > MAX_MESSAGE_LEN:
        text = text[: MAX_MESSAGE_LEN - 1].rstrip() + "\u2026"
    return text or "(left no message)"


def parse_issue_form_body(body):
    """Issue forms render as '### Field\\n\\nvalue' blocks. We only
    care about the single free-text field defined in the template."""
    match = re.search(r"### Message\s*\n+([\s\S]*?)(\n###|\Z)", body or "")
    return match.group(1).strip() if match else (body or "")


def gh_request(method, path, token, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        f"{API_ROOT}{path}",
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "SKYLORD69-PY-profile-bot",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
        return json.loads(raw.decode()) if raw else None


def load_entries(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def render_markdown(entries):
    lines = [
        "# \U0001F4D6 Guestbook",
        "",
        "Signed via the **Guestbook Entry** issue form. Newest first.",
        "",
        "| Visitor | Message |",
        "|:--|:--|",
    ]
    for entry in entries[-MAX_SHOWN:][::-1]:
        lines.append(f"| [@{entry['user']}](https://github.com/{entry['user']}) | {entry['message']} |")
    return "\n".join(lines) + "\n"


def main():
    token = os.environ.get("GITHUB_TOKEN")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    repo = os.environ.get("GITHUB_REPOSITORY")  # "owner/repo", auto-provided

    if not token or not event_path or not repo:
        print("::error::Missing GITHUB_TOKEN, GITHUB_EVENT_PATH, or GITHUB_REPOSITORY.",
              file=sys.stderr)
        sys.exit(1)

    with open(event_path, "r", encoding="utf-8") as f:
        event = json.load(f)

    issue = event.get("issue", {})
    issue_number = issue.get("number")
    author = issue.get("user", {}).get("login", "anonymous")
    raw_message = parse_issue_form_body(issue.get("body", ""))
    message = sanitize(raw_message)

    entries = load_entries(GUESTBOOK_JSON)
    entries.append({"user": author, "message": message, "issue": issue_number})

    os.makedirs(os.path.dirname(GUESTBOOK_JSON), exist_ok=True)
    with open(GUESTBOOK_JSON, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)

    with open(GUESTBOOK_MD, "w", encoding="utf-8") as f:
        f.write(render_markdown(entries))

    # Best-effort niceties -- a failure here should never crash the
    # actual guestbook write above, which is why these are separate,
    # individually-guarded calls instead of one big try block.
    try:
        gh_request("POST", f"/repos/{repo}/issues/{issue_number}/reactions", token,
                   {"content": "heart"})
    except Exception as e:  # noqa: BLE001
        print(f"::warning::Could not react to issue #{issue_number}: {e}")

    try:
        gh_request("PATCH", f"/repos/{repo}/issues/{issue_number}", token, {"state": "closed"})
        gh_request("PUT", f"/repos/{repo}/issues/{issue_number}/lock", token, {"lock_reason": "resolved"})
    except Exception as e:  # noqa: BLE001
        print(f"::warning::Could not close/lock issue #{issue_number}: {e}")

    print(f"Guestbook entry #{len(entries)} recorded from @{author}.")


if __name__ == "__main__":
    main()
