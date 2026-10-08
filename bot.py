import json
import urllib.request

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


def get_token():
    request = urllib.request.Request(
        "https://pam-stilling-feed.nav.no/api/publicToken",
        headers={"User-Agent": "job-bot/1.0"}
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        token = response.read().decode("utf-8").strip()

    # Token may be returned as plain text or as a JSON string
    if token.startswith('"') and token.endswith('"'):
        token = json.loads(token)

    return token


def get_feed(token):
    request = urllib.request.Request(
        "https://pam-stilling-feed.nav.no/api/v1/feed",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "job-bot/1.0"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def matches(job):
    feed_entry = job.get("_feed_entry", {})

    text = " ".join([
        str(job.get("title", "")),
        str(job.get("content_text", "")),
        str(feed_entry.get("businessName", ""))
    ]).lower()

    if any(word in text for word in EXCLUDE):
        return False

    return any(word in text for word in KEYWORDS)


def main():
    print("Getting NAV token...")
    token = get_token()

    if not token:
        raise RuntimeError("NAV public token is empty")

    print("Getting job feed...")
    data = get_feed(token)

    found = []

    for job in data.get("items", []):
        feed_entry = job.get("_feed_entry", {})

        if feed_entry.get("status") != "ACTIVE":
            continue

        if matches(job):
            found.append({
                "id": job.get("id"),
                "title": job.get("title"),
                "company": feed_entry.get("businessName"),
                "url": job.get("url"),
                "date": job.get("date_modified")
            })

    print(f"Found {len(found)} matching jobs")

    for job in found:
        print(json.dumps(job, ensure_ascii=False))


if __name__ == "__main__":
    main()
