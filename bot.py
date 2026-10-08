import json
import re
import urllib.request
import urllib.parse
from datetime import datetime, timezone


# ============================================================
# НАСТРОЙКИ
# ============================================================

KEYWORDS = [
    # FARM / AGRICULTURE
    "farm",
    "farmer",
    "farm worker",
    "farmhand",
    "agriculture",
    "agricultural",
    "livestock",
    "animal",
    "animals",
    "greenhouse",
    "gardener",
    "gardening",
    "fruit",
    "berry",
    "harvest",
    "seasonal",

    # FORESTRY / WOOD
    "forestry",
    "forest",
    "forest worker",
    "forestry worker",
    "logger",
    "logging",
    "chainsaw",
    "wood",
    "sawmill",
    "timber",

    # WAREHOUSE / PRODUCTION
    "warehouse",
    "warehouse worker",
    "warehouse operative",
    "production worker",
    "factory worker",
    "production",
    "packing",
    "packer",
    "packing worker",
    "picker",
    "order picker",

    # GENERAL PHYSICAL WORK
    "labourer",
    "laborer",
    "general worker",
    "worker",
    "seasonal worker",
    "manual worker",
]


EXCLUDE = [
    "software engineer",
    "software developer",
    "developer",
    "programmer",
    "frontend",
    "backend",
    "full stack",
    "devops",
    "data scientist",
    "doctor",
    "dentist",
    "lawyer",
    "accountant",
    "architect",
    "surgeon",
]


BASE_URL = "https://pam-stilling-feed.nav.no"

FEED_URL = (
    "https://pam-stilling-feed.nav.no/api/v1/feed"
)

PUBLIC_TOKEN_URL = (
    "https://pam-stilling-feed.nav.no/api/publicToken"
)

# Сколько страниц feed проверять за один запуск.
# 5 = быстро и безопасно для GitHub Actions.
MAX_PAGES = 5


# ============================================================
# HTTP
# ============================================================

def http_get(url, headers=None):
    """
    GET-запрос.
    Возвращает HTTP status, headers и body.
    """

    request = urllib.request.Request(
        url,
        headers=headers or {
            "User-Agent": "job-bot/1.0"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        status = response.status
        response_headers = dict(response.headers)
        body = response.read()

    return status, response_headers, body


# ============================================================
# NAV TOKEN
# ============================================================

def get_nav_token():
    """
    NAV возвращает примерно:

    *** public token for Nav Job Vacancy Feed:
    eyJxxxxx.yyyyy.zzzzz

    Нам нужен только JWT.
    """

    print("Getting NAV public token...")

    status, headers, body = http_get(
        PUBLIC_TOKEN_URL,
        {
            "User-Agent": "job-bot/1.0",
            "Accept": "*/*"
        }
    )

    text = body.decode("utf-8", errors="replace").strip()

    if status != 200:
        raise RuntimeError(
            f"NAV token request failed: HTTP {status}"
        )

    if not text:
        raise RuntimeError(
            "NAV returned an empty token response"
        )

    # Ищем настоящий JWT.
    #
    # JWT обычно выглядит так:
    # eyJ....eyJ....xxxxx
    #
    # Поэтому НЕ используем весь ответ NAV.
    match = re.search(
        r"(eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)",
        text
    )

    if not match:
        print("NAV token response:")
        print(text[:500])

        raise RuntimeError(
            "Could not find JWT token in NAV response"
        )

    token = match.group(1)

    print("NAV token obtained successfully.")

    return token


# ============================================================
# GET FEED PAGE
# ============================================================

def get_feed_page(url, token):
    """
    Получает одну страницу NAV feed.
    """

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "job-bot/1.0"
    }

    status, response_headers, body = http_get(
        url,
        headers
    )

    if status != 200:
        raise RuntimeError(
            f"NAV feed request failed: HTTP {status}"
        )

    try:
        data = json.loads(
            body.decode("utf-8")
        )
    except json.JSONDecodeError as error:
        print("NAV returned invalid JSON:")
        print(body[:1000])

        raise RuntimeError(
            f"Could not decode NAV feed JSON: {error}"
        )

    return data


# ============================================================
# NORMALIZE URL
# ============================================================

def absolute_url(url):
    """
    Делает URL абсолютным, если NAV вернул относительный.
    """

    if not url:
        return None

    if url.startswith("http://"):
        return url

    if url.startswith("https://"):
        return url

    return urllib.parse.urljoin(
        BASE_URL,
        url
    )


# ============================================================
# MATCHING
# ============================================================

def job_text(job):
    """
    Собирает весь доступный текст вакансии
    для поиска ключевых слов.
    """

    feed_entry = job.get(
        "_feed_entry",
        {}
    )

    parts = [
        job.get("title", ""),
        job.get("content_text", ""),
        feed_entry.get("title", ""),
        feed_entry.get("businessName", ""),
        feed_entry.get("municipal", ""),
    ]

    return " ".join(
        str(x)
        for x in parts
        if x
    ).lower()


def matches_job(job):
    """
    Проверяет, подходит ли вакансия.
    """

    text = job_text(job)

    # Сначала исключения.
    for word in EXCLUDE:
        if word in text:
            return False

    # Потом ключевые слова.
    for word in KEYWORDS:
        if word in text:
            return True

    return False


# ============================================================
# GET FULL JOB DETAILS
# ============================================================

def get_job_details(job, token):
    """
    NAV feed item содержит URL,
    по которому можно получить полную вакансию.
    """

    url = absolute_url(
        job.get("url")
    )

    if not url:
        return {}

    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "job-bot/1.0"
        }

        status, response_headers, body = http_get(
            url,
            headers
        )

        if status != 200:
            print(
                f"Could not get job details: HTTP {status}"
            )
            return {}

        return json.loads(
            body.decode("utf-8")
        )

    except Exception as error:
        print(
            f"Could not get job details: {error}"
        )

        return {}


# ============================================================
# EXTRACT CONTACTS
# ============================================================

def extract_contacts(details):
    """
    Достаёт email и телефон работодателя.
    """

    contacts = []

    content = details.get(
        "ad_content",
        details
    )

    contact_list = content.get(
        "contactList",
        []
    )

    if not isinstance(
        contact_list,
        list
    ):
        return contacts

    for contact in contact_list:

        if not isinstance(
            contact,
            dict
        ):
            continue

        contacts.append({
            "name": contact.get(
                "name"
            ),
            "email": contact.get(
                "email"
            ),
            "phone": contact.get(
                "phone"
            ),
            "role": contact.get(
                "role"
            ),
            "title": contact.get(
                "title"
            ),
        })

    return contacts


# ============================================================
# EXTRACT APPLICATION URL
# ============================================================

def extract_application_url(details):
    """
    NAV обычно хранит ссылку для подачи заявки
    в applicationUrl.
    """

    content = details.get(
        "ad_content",
        details
    )

    application_url = content.get(
        "applicationUrl"
    )

    if application_url:
        return application_url

    # Иногда полезная ссылка может находиться здесь.
    link = content.get(
        "link"
    )

    if link:
        return link

    return None


# ============================================================
# PROCESS JOB
# ============================================================

def process_job(job, token):
    """
    Превращает NAV vacancy в нормальный объект.
    """

    feed_entry = job.get(
        "_feed_entry",
        {}
    )

    details = get_job_details(
        job,
        token
    )

    content = details.get(
        "ad_content",
        details
    )

    employer = content.get(
        "employer",
        {}
    )

    if not isinstance(
        employer,
        dict
    ):
        employer = {}

    work_locations = content.get(
        "workLocations",
        []
    )

    if not isinstance(
        work_locations,
        list
    ):
        work_locations = []

    location = None

    if work_locations:
        first_location = work_locations[0]

        if isinstance(
            first_location,
            dict
        ):
            location = {
                "country": first_location.get(
                    "country"
                ),
                "city": first_location.get(
                    "city"
                ),
                "municipal": first_location.get(
                    "municipal"
                ),
                "address": first_location.get(
                    "address"
                ),
            }

    result = {
        "id": job.get("id"),

        "title": (
            content.get("title")
            or job.get("title")
        ),

        "company": (
            employer.get("name")
            or feed_entry.get(
                "businessName"
            )
        ),

        "organization_number": (
            employer.get("orgnr")
        ),

        "location": location,

        "job_url": absolute_url(
            job.get("url")
        ),

        "application_url": (
            extract_application_url(
                details
            )
        ),

        "source_url": content.get(
            "sourceurl"
        ),

        "description": content.get(
            "description"
        ),

        "employment_type": content.get(
            "engagementtype"
        ),

        "extent": content.get(
            "extent"
        ),

        "start_time": content.get(
            "starttime"
        ),

        "position_count": content.get(
            "positioncount"
        ),

        "application_deadline": content.get(
            "applicationDue"
        ),

        "homepage": employer.get(
            "homepage"
        ),

        "contacts": extract_contacts(
            details
        ),

        "date_modified": job.get(
            "date_modified"
        ),
    }

    return result


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("JOB BOT STARTED")
    print("=" * 60)

    # --------------------------------------------------------
    # 1. TOKEN
    # --------------------------------------------------------

    token = get_nav_token()

    # --------------------------------------------------------
    # 2. FEED
    # --------------------------------------------------------

    print("Getting NAV job feed...")

    next_url = FEED_URL

    found_jobs = []

    seen_ids = set()

    # --------------------------------------------------------
    # 3. PAGES
    # --------------------------------------------------------

    for page_number in range(
        1,
        MAX_PAGES + 1
    ):

        if not next_url:
            break

        print(
            f"Checking feed page {page_number}..."
        )

        data = get_feed_page(
            next_url,
            token
        )

        items = data.get(
            "items",
            []
        )

        print(
            f"Jobs on page: {len(items)}"
        )

        for job in items:

            job_id = job.get(
                "id"
            )

            if not job_id:
                continue

            if job_id in seen_ids:
                continue

            seen_ids.add(
                job_id
            )

            feed_entry = job.get(
                "_feed_entry",
                {}
            )

            status = feed_entry.get(
                "status"
            )

            # Только активные вакансии.
            if status != "ACTIVE":
                continue

            # Проверяем ключевые слова.
            if not matches_job(job):
                continue

            print(
                "MATCH:",
                job.get("title")
            )

            try:

                full_job = process_job(
                    job,
                    token
                )

                found_jobs.append(
                    full_job
                )

            except Exception as error:

                print(
                    "Error processing job:",
                    error
                )

        # ----------------------------------------------------
        # NEXT PAGE
        # ----------------------------------------------------

        next_url = data.get(
            "next_url"
        )

        if next_url:
            next_url = absolute_url(
                next_url
            )

    # --------------------------------------------------------
    # 4. REMOVE DUPLICATES
    # --------------------------------------------------------

    unique_jobs = {}

    for job in found_jobs:

        job_id = job.get(
            "id"
        )

        if job_id:
            unique_jobs[job_id] = job

    found_jobs = list(
        unique_jobs.values()
    )

    # --------------------------------------------------------
    # 5. SAVE RESULTS
    # --------------------------------------------------------

    output = {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),

        "count": len(
            found_jobs
        ),

        "jobs": found_jobs
    }

    with open(
        "jobs.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2
        )

    # --------------------------------------------------------
    # 6. PRINT RESULTS
    # --------------------------------------------------------

    print("")
    print("=" * 60)
    print(
        f"FOUND {len(found_jobs)} MATCHING JOBS"
    )
    print("=" * 60)

    for number, job in enumerate(
        found_jobs,
        start=1
    ):

        print("")
        print(
            f"#{number} {job.get('title')}"
        )

        print(
            "Company:",
            job.get("company")
        )

        location = job.get(
            "location"
        )

        if location:
            print(
                "Location:",
                location.get("city")
                or location.get("municipal")
            )

        print(
            "Job:",
            job.get("job_url")
        )

        print(
            "APPLY:",
            job.get(
                "application_url"
            )
        )

        contacts = job.get(
            "contacts",
            []
        )

        for contact in contacts:

            if contact.get("email"):
                print(
                    "EMAIL:",
                    contact.get("email")
                )

            if contact.get("phone"):
                print(
                    "PHONE:",
                    contact.get("phone")
                )

    print("")
    print("=" * 60)
    print("JOB BOT FINISHED")
    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
