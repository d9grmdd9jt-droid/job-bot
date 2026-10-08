import json
import urllib.request
import urllib.parse
import re
from datetime import datetime, timezone

KEYWORDS = [
    "farm", "farmer", "agriculture", "agricultural",
    "forestry", "forest", "forest worker", "logger",
    "chainsaw", "wood", "sawmill", "harvest",
    "warehouse", "warehouse worker", "production",
    "seasonal", "farm worker", "fruit", "berry"
]

EXCLUDE = [
    "engineer", "developer", "programmer", "doctor",
    "lawyer", "manager", "accountant"
]

def get_json(url, headers=None):
    request = urllib.request.Request(
        url,
        headers=headers or {"User-Agent": "job-bot/1.0"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))

def get_nav_token():
    data = get_json("https://pam-stilling-feed.nav.no/api/publicToken")
    if isinstance(data, str):
        return data
    return data.get("token") or data.get("access_token")

def matches(job):
    text = " ".join([
        str(job.get("title", "")),
        str(job.get("content_text", "")),
        str(job.get("_feed_entry", {}).get("businessName", ""))
    ]).lower()

    if any(word in text for word in EXCLUDE):
        return False

    return any(word in text for word in KEYWORDS)

def main():
    token = get_nav_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "job-bot/1.0"
    }

    data = get_json(
        "https://pam-stilling-feed.nav.no/api/v1/feed",
        headers
    )

    found = []

    for job in data.get("items", []):
        if job.get("_feed_entry", {}).get("status") != "ACTIVE":
            continue

        if matches(job):
            found.append({
                "id": job.get("id"),
                "title": job.get("title"),
                "company": job.get("_feed_entry", {}).get("businessName"),
                "url": job.get("url"),
                "date": job.get("date_modified")
            })

    print(json.dumps(found, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
