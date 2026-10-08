import json
import re
import urllib.request
import urllib.parse
import unicodedata
from datetime import datetime, timezone


# ============================================================
# НАСТРОЙКИ
# ============================================================

FEED_URL = "https://pam-stilling-feed.nav.no/api/v1/feed"
TOKEN_URL = "https://pam-stilling-feed.nav.no/api/publicToken"

MAX_PAGES = 10


# ============================================================
# КЛЮЧЕВЫЕ СЛОВА
# НОРВЕЖСКИЙ + АНГЛИЙСКИЙ
# ============================================================

KEYWORDS = [

    # FARM / AGRICULTURE
    "farm",
    "farmer",
    "farm worker",
    "farmhand",
    "agriculture",
    "agricultural",
    "agricultural worker",

    "gård",
    "gårdsarbeid",
    "gårdsarbeider",
    "gårdsarbeidere",
    "landbruk",
    "landbruksarbeider",
    "landbruksarbeid",
    "jordbruk",
    "jordbruksarbeider",
    "jordbruksarbeid",

    # ANIMALS
    "livestock",
    "animal",
    "animals",
    "animal care",
    "dyrehold",
    "dyrestell",
    "dyrepasser",
    "dyrepleier",
    "fjøs",
    "avløser",
    "røkter",
    "husdyr",

    # GREENHOUSE / GARDEN
    "greenhouse",
    "gardener",
    "gardening",
    "gartner",
    "gartnerarbeid",
    "veksthus",
    "plante",
    "planter",
    "hagearbeid",

    # FRUIT / BERRIES / HARVEST
    "fruit",
    "berry",
    "berries",
    "harvest",
    "seasonal",
    "seasonal worker",
    "frukt",
    "bær",
    "innhøsting",
    "sesong",
    "sesongarbeid",
    "sesongarbeider",
    "sesongarbeidere",

    # FORESTRY
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

    "skog",
    "skogbruk",
    "skogarbeid",
    "skogarbeider",
    "skogsarbeider",
    "skogbruksarbeider",
    "hogst",
    "tømmer",
    "tømmerhogst",
    "ved",
    "vedproduksjon",
    "sagbruk",
    "trevirke",

    # WAREHOUSE
    "warehouse",
    "warehouse worker",
    "warehouse operative",
    "warehouse assistant",
    "lager",
    "lagerarbeider",
    "lagermedarbeider",
    "lagerarbeid",
    "lagerjobb",
    "varelager",
    "logistikk",
    "plukker",
    "ordreplukker",
    "pakker",
    "pakking",
    "vareplukk",

    # PRODUCTION / FACTORY
    "production worker",
    "production operative",
    "factory worker",
    "production",
    "factory",
    "packing",
    "packer",
    "picker",
    "manufacturing",

    "produksjon",
    "produksjonsarbeid",
    "produksjonsarbeider",
    "produksjonsmedarbeider",
    "fabrikk",
    "fabrikkarbeider",
    "industriproduksjon",
    "pakking",
    "pakker",
    "pakking",
    "sortering",
    "sorteringsarbeid",

    # GENERAL PHYSICAL WORK
    "labourer",
    "laborer",
    "general worker",
    "manual worker",
    "physical work",

    "arbeider",
    "arbeidsmann",
    "hjelpearbeider",
    "håndverker",
    "manuelt arbeid",
    "fysisk arbeid",
    "praktisk arbeid",

    # CONSTRUCTION / OUTDOOR
    "construction worker",
    "construction",
    "anleggsarbeider",
    "anleggsarbeid",
    "byggarbeider",
    "byggearbeid",
    "utearbeid",
    "utendørsarbeid",

    # MACHINE / TRACTOR
    "tractor",
    "tractor driver",
    "machine operator",
    "maskinfører",
    "maskinoperatør",
    "traktorfører",
    "traktor",
]


# ============================================================
# СЛОВА, КОТОРЫЕ ЧАСТО ОЗНАЧАЮТ НЕПОДХОДЯЩУЮ ПРОФЕССИЮ
# ============================================================

EXCLUDE = [

    # IT
    "software engineer",
    "software developer",
    "developer",
    "programmer",
    "programmering",
    "frontend",
    "backend",
    "full stack",
    "devops",
    "data scientist",
    "data engineer",
    "systemutvikler",
    "systemutvikling",
    "it-konsulent",
    "it konsulent",

    # MEDICAL
    "doctor",
    "dentist",
    "doctorate",
    "lege",
    "tannlege",
    "sykepleier",
    "sykepleie",
    "kirurg",

    # LAW
    "lawyer",
    "jurist",
    "advokat",

    # FINANCE
    "accountant",
    "accounting",
    "regnskapsfører",
    "regnskap",

    # HIGH-SKILL OFFICE
    "architect",
    "arkitekt",
    "financial analyst",
    "analytiker",
    "controller",
]


# ============================================================
# HTTP
# ============================================================

def http_get(url, headers=None):

    request = urllib.request.Request(
        url,
        headers=headers or {
            "User-Agent": "job-bot/1.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        return (
            response.status,
            dict(response.headers),
            response.read()
        )


# ============================================================
# НОРМАЛИЗАЦИЯ ТЕКСТА
# ============================================================

def normalize(text):

    if not text:
        return ""

    text = str(text).lower()

    # Убираем HTML
    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    # Нормализация Unicode
    text = unicodedata.normalize(
        "NFKC",
        text
    )

    # Пробелы
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# TOKEN
# ============================================================

def get_token():

    print("Getting NAV public token...")

    status, headers, body = http_get(
        TOKEN_URL,
        {
            "User-Agent": "job-bot/1.0",
            "Accept": "*/*"
        }
    )

    text = body.decode(
        "utf-8",
        errors="replace"
    ).strip()

    if status != 200:
        raise RuntimeError(
            f"NAV token error: HTTP {status}"
        )

    # NAV отдаёт текст перед JWT.
    # Ищем только настоящий JWT.
    match = re.search(
        r"(eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)",
        text
    )

    if not match:
        raise RuntimeError(
            "Could not find JWT token in NAV response"
        )

    token = match.group(1)

    print("NAV token obtained successfully.")

    return token


# ============================================================
# FEED
# ============================================================

def get_feed(url, token):

    status, headers, body = http_get(
        url,
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "job-bot/1.0"
        }
    )

    if status != 200:
        raise RuntimeError(
            f"NAV feed error: HTTP {status}"
        )

    try:
        return json.loads(
            body.decode("utf-8")
        )

    except json.JSONDecodeError as error:

        print(
            body[:1000]
        )

        raise RuntimeError(
            f"Invalid NAV JSON: {error}"
        )


# ============================================================
# URL
# ============================================================

def absolute_url(url):

    if not url:
        return None

    if url.startswith("http://"):
        return url

    if url.startswith("https://"):
        return url

    return urllib.parse.urljoin(
        "https://pam-stilling-feed.nav.no/",
        url
    )


# ============================================================
# СОБИРАЕМ ТЕКСТ ВАКАНСИИ
# ============================================================

def get_search_text(job):

    feed = job.get(
        "_feed_entry",
        {}
    )

    text = " ".join([
        str(job.get("title", "")),
        str(job.get("content_text", "")),
        str(feed.get("title", "")),
        str(feed.get("businessName", "")),
        str(feed.get("municipal", "")),
    ])

    return normalize(text)


# ============================================================
# ПОИСК ПОДХОДЯЩЕЙ ВАКАНСИИ
# ============================================================

def matches(job):

    text = get_search_text(job)

    # Сначала исключения
    for word in EXCLUDE:

        if normalize(word) in text:
            return False

    # Потом подходящие слова
    for word in KEYWORDS:

        if normalize(word) in text:
            return True

    return False


# ============================================================
# ПОЛНАЯ ИНФОРМАЦИЯ О ВАКАНСИИ
# ============================================================

def get_details(job, token):

    url = absolute_url(
        job.get("url")
    )

    if not url:
        return {}

    try:

        status, headers, body = http_get(
            url,
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "job-bot/1.0"
            }
        )

        if status != 200:
            return {}

        return json.loads(
            body.decode("utf-8")
        )

    except Exception as error:

        print(
            f"Details error: {error}"
        )

        return {}


# ============================================================
# ИЗВЛЕЧЕНИЕ ДАННЫХ
# ============================================================

def build_job(job, token):

    feed = job.get(
        "_feed_entry",
        {}
    )

    details = get_details(
        job,
        token
    )

    content = details.get(
        "ad_content",
        details
    )

    if not isinstance(
        content,
        dict
    ):
        content = {}

    employer = content.get(
        "employer",
        {}
    )

    if not isinstance(
        employer,
        dict
    ):
        employer = {}

    contacts = content.get(
        "contactList",
        []
    )

    if not isinstance(
        contacts,
        list
    ):
        contacts = []

    clean_contacts = []

    for contact in contacts:

        if not isinstance(
            contact,
            dict
        ):
            continue

        clean_contacts.append({
            "name": contact.get("name"),
            "email": contact.get("email"),
            "phone": contact.get("phone"),
            "role": contact.get("role"),
        })

    locations = content.get(
        "workLocations",
        []
    )

    if not isinstance(
        locations,
        list
    ):
        locations = []

    location = None

    if locations:

        first = locations[0]

        if isinstance(
            first,
            dict
        ):
            location = {
                "country": first.get("country"),
                "city": first.get("city"),
                "municipal": first.get("municipal"),
                "address": first.get("address"),
            }

    application_url = (
        content.get("applicationUrl")
        or content.get("applicationUrl")
    )

    return {

        "id": job.get("id"),

        "title": (
            content.get("title")
            or job.get("title")
        ),

        "company": (
            employer.get("name")
            or feed.get("businessName")
        ),

        "location": location,

        "job_url": absolute_url(
            job.get("url")
        ),

        "application_url": application_url,

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

        "deadline": content.get(
            "applicationDue"
        ),

        "homepage": employer.get(
            "homepage"
        ),

        "contacts": clean_contacts,

        "date_modified": job.get(
            "date_modified"
        ),
    }


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("JOB BOT STARTED")
    print("=" * 60)

    token = get_token()

    print("Getting NAV job feed...")

    next_url = FEED_URL

    found = []

    seen = set()

    total_active = 0

    total_checked = 0

    for page in range(
        1,
        MAX_PAGES + 1
    ):

        if not next_url:
            break

        print(
            f"Checking feed page {page}..."
        )

        data = get_feed(
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

            total_checked += 1

            job_id = job.get(
                "id"
            )

            if not job_id:
                continue

            if job_id in seen:
                continue

            seen.add(job_id)

            feed = job.get(
                "_feed_entry",
                {}
            )

            if feed.get("status") != "ACTIVE":
                continue

            total_active += 1

            if matches(job):

                print(
                    "MATCH:",
                    job.get("title")
                )

                full = build_job(
                    job,
                    token
                )

                found.append(full)

        next_url = data.get(
            "next_url"
        )

        if next_url:
            next_url = absolute_url(
                next_url
            )

    # ========================================================
    # УДАЛЯЕМ ДУБЛИКАТЫ
    # ========================================================

    unique = {}

    for job in found:

        if job.get("id"):
            unique[job["id"]] = job

    found = list(
        unique.values()
    )

    # ========================================================
    # СОХРАНЯЕМ
    # ========================================================

    result = {

        "generated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "pages_checked":
            MAX_PAGES,

        "jobs_checked":
            total_checked,

        "active_jobs_checked":
            total_active,

        "matching_jobs":
            len(found),

        "jobs":
            found,
    }

    with open(
        "jobs.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2
        )

    # ========================================================
    # РЕЗУЛЬТАТ
    # ========================================================

    print("")
    print("=" * 60)
    print(
        f"CHECKED {total_checked} JOBS"
    )
    print(
        f"ACTIVE {total_active} JOBS"
    )
    print(
        f"FOUND {len(found)} MATCHING JOBS"
    )
    print("=" * 60)

    for number, job in enumerate(
        found,
        1
    ):

        print("")
        print(
            f"#{number} {job.get('title')}"
        )

        print(
            "Company:",
            job.get("company")
        )

        print(
            "Job:",
            job.get("job_url")
        )

        print(
            "APPLY:",
            job.get("application_url")
        )

        for contact in job.get(
            "contacts",
            []
        ):

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


if __name__ == "__main__":
    main()
