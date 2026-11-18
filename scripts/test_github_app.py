# SPDX-License-Identifier: AGPL-3.0-only

import os
import time
from pathlib import Path

import jwt
import requests

app_id = os.environ["GITHUB_APP_ID"]
installation_id = os.environ["GITHUB_INSTALLATION_ID"]
private_key = Path(
    os.environ["GITHUB_PRIVATE_KEY_PATH"]
).read_text()

now = int(time.time())

app_jwt = jwt.encode(
    {
        "iat": now - 60,
        "exp": now + 540,
        "iss": app_id,
    },
    private_key,
    algorithm="RS256",
)

headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {app_jwt}",
    "X-GitHub-Api-Version": "2026-03-10",
}

session = requests.Session()
session.timeout = 30

response = session.post(
    f"https://api.github.com/app/installations/"
    f"{installation_id}/access_tokens",
    headers=headers,
    timeout=30,
)
response.raise_for_status()

installation_token = response.json()["token"]

api_headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {installation_token}",
    "X-GitHub-Api-Version": "2026-03-10",
}

response = session.get(
    "https://api.github.com/installation/repositories",
    headers=api_headers,
    timeout=30,
)
response.raise_for_status()

data = response.json()
print("Repositories visible:", data["total_count"])

for repo in data["repositories"]:
    print(repo["full_name"])

response = session.get(
    "https://api.github.com/orgs/Happili-platform/installations",
    headers=api_headers,
    timeout=30,
)

print("Installed apps inventory status:", response.status_code)

if response.ok:
    print("Installed app count:", response.json()["total_count"])
else:
    print(
        "Installed app inventory requires authorization review:",
        response.text[:500],
    )

