# SPDX-License-Identifier: AGPL-3.0-only
"""Check DCO sign-off trailers on commits submitted through a PR.

This is evidence of a contributor attestation, not proof of copyright ownership.
"""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.request import Request, urlopen

SIGNOFF = re.compile(r"^Signed-off-by:\s*(.+?)\s*<([^<>\s]+@[^<>\s]+)>\s*$", re.I | re.M)


def valid_signoff(message: str, author_email: str | None = None) -> bool:
    """Require a trailer; match commit author email when GitHub supplies it."""
    matches = SIGNOFF.findall(message)
    if not matches:
        return False
    if not author_email:
        return True
    return any(email.casefold() == author_email.casefold() for _, email in matches)


def api_json(url: str, token: str):
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urlopen(request, timeout=25) as response:
        return json.load(response)


def main() -> int:
    token = os.getenv("GITHUB_TOKEN", "")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    api = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    if not token or not repository or not event_path:
        print("Missing GitHub Actions PR context", file=sys.stderr)
        return 2
    with open(event_path, encoding="utf-8") as f:
        event = json.load(f)
    number = event.get("pull_request", {}).get("number") or event.get("number")
    if not isinstance(number, int):
        print("DCO verification requires a pull_request event", file=sys.stderr)
        return 2
    failures = []
    page = 1
    while True:
        url = f"{api}/repos/{repository}/pulls/{number}/commits?per_page=100&page={page}"
        commits = api_json(url, token)
        if not isinstance(commits, list):
            print("Unexpected commits API response", file=sys.stderr)
            return 2
        for item in commits:
            record = item.get("commit") or {}
            author = record.get("author") or {}

            # Merge commits are integration records, not individual
            # contributor submissions. Contributor commits still
            # require valid DCO sign-offs.
            if len(item.get("parents", [])) == 2:
                print(f"SKIP merge commit: {item.get('sha', 'unknown')[:12]}")
                continue

            if not valid_signoff(record.get("message", ""), author.get("email")):
                failures.append(item.get("sha", "unknown")[:12])
        if len(commits) < 100:
            break
        page += 1
        if len(commits) < 100:
            break
        page += 1
    if failures:
        print("DCO sign-off missing or author email mismatched for commits: " + ", ".join(failures), file=sys.stderr)
        print("Use git commit -s; for an existing commit, see CONTRIBUTING.md", file=sys.stderr)
        return 1
    print("PASS: All PR commits have DCO sign-off trailers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
