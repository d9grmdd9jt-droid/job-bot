import json
import os
import re
import time
import urllib.error
import urllib.request
import urllib.parse
import unicodedata
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime


# ============================================================
# CONFIG
# ============================================================

NAV_FEED_URL = "https://pam-stilling-feed.nav.no/api/v1/feed"
NAV_TOKEN_URL = "https://pam-stilling-feed.nav.no/api/publicToken"

STATE_FILE = "nav_state.json"
JOBS_FILE = "jobs.json"

# Первая синхронизация:
# NAV указывает, что активная вакансия не живёт больше 6 месяцев.
INITIAL_LOOKBACK_DAYS = 180

# При каждом следующем запуске берём небольшой запас назад,
# чтобы не потерять изменения между двумя запусками.
OVERLAP_MINUTES = 10

# Защита от бесконечного цикла.
MAX_PAGES_PER_RUN = 500

# HTTP retry.
MAX_RETRIES = 5

# Не делать слишком много запросов подряд.
REQUEST_DELAY = 0.05


# ============================================================
# ПОИСКОВЫЕ СЛОВА
# ============================================================

# Сильные признаки нужной нам работы.
STRONG_KEYWORDS = [

    # FARM
    "farm",
    "farmer",
    "farmhand",
    "farm worker",
    "farm work",
    "agriculture",
    "agricultural",
    "agricultural worker",

    "gård",
    "gårdsarbeid",
    "gårdsarbeider",
    "gårdsarbeidere",
    "landbruk",
    "landbruksarbeid",
    "landbruksarbeider",
    "jordbruk",
    "jordbruksarbeid",
    "jordbruksarbeider",

    # ANIMALS
    "livestock",
    "animal care",
    "animal worker",
    "animal husbandry",

    "dyrehold",
    "dyrestell",
    "dyrepasser",
    "dyrepleier",
    "fjøs",
    "fjos",
    "avløser",
    "avloser",
    "røkter",
    "rokter",
    "husdyr",

    # GREENHOUSE / GARDEN
    "greenhouse",
    "gardener",
    "gardening",
    "horticulture",

    "gartner",
    "gartnerarbeid",
    "veksthus",
    "planteproduksjon",
    "plante",
    "planter",
    "hagearbeid",

    # FRUIT / BERRIES / HARVEST
    "fruit",
    "berry",
    "berries",
    "harvest",
    "harvesting",
    "seasonal worker",
    "seasonal work",

    "frukt",
    "bær",
    "innhøsting",
    "sesongarbeid",
    "sesongarbeider",
    "sesongarbeidere",

    # FORESTRY
    "forestry",
    "forest worker",
    "forestry worker",
    "logging",
    "logger",
    "chainsaw",
    "wood worker",
    "woodwork",
    "sawmill",
    "timber",

    "skogbruk",
    "skogarbeid",
    "skogarbeider",
    "skogsarbeider",
    "skogbruksarbeider",
    "skogbruker",
    "hogst",
    "tømmer",
    "tommer",
    "tømmerhogst",
    "tommerhogst",
    "sagbruk",
    "trevirke",
    "vedproduksjon",

    # WAREHOUSE / LOGISTICS
    "warehouse",
    "warehouse worker",
    "warehouse operative",
    "warehouse assistant",
    "order picker",
    "picker",
    "packer",
    "packing",

    "lager",
    "lagerarbeid",
    "lagerarbeider",
    "lagermedarbeider",
    "lagerjobb",
    "varelager",
    "vareplukk",
    "ordreplukk",
    "ordreplukker",
    "plukker",
    "pakker",
    "pakking",

    # PRODUCTION
    "production worker",
    "production operative",
    "factory worker",
    "factory",
    "manufacturing",
    "production",

    "produksjon",
    "produksjonsarbeid",
    "produksjonsarbeider",
    "produksjonsmedarbeider",
    "fabrikk",
    "fabrikkarbeider",
    "industriproduksjon",
    "sortering",
    "sorteringsarbeid",

    # PHYSICAL / OUTDOOR
    "labourer",
    "laborer",
    "manual worker",
    "manual labour",
    "manual labor",
    "physical work",
    "general worker",

    "hjelpearbeider",
    "hjelpearbeid",
    "manuelt arbeid",
    "fysisk arbeid",
    "praktisk arbeid",
    "ute arbeid",
    "utearbeid",
    "utendørsarbeid",

    # CONSTRUCTION / OUTDOOR
    "construction worker",
    "construction labourer",
    "construction laborer",
    "anlegg",
    "anleggsarbeid",
    "anleggsarbeider",
    "byggarbeid",
    "byggarbeider",

    # MACHINES / TRACTOR
    "tractor driver",
    "tractor operator",
    "machine operator",
    "machine operator",
    "traktorfører",
    "traktorforer",
    "maskinfører",
    "maskinforer",
    "maskinoperatør",
    "maskinoperator",
]


# Слова, которые сами по себе не должны считаться совпадением,
# но могут усилить результат вместе с контекстом.
GENERIC_KEYWORDS = [
    "worker",
    "arbeider",
    "arbeid",
    "operator",
    "operatør",
    "medarbeider",
    "hjelper",
]


# Если эти слова находятся именно в TITLE/JOB TITLE,
# вакансия обычно не подходит под нашу задачу.
TITLE_EXCLUDE = [
    "software",
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
    "it-konsulent",

    "doctor",
    "dentist",
    "lege",
    "tannlege",
    "sykepleier",
    "kirurg",

    "lawyer",
    "jurist",
    "advokat",

    "accountant",
    "regnskapsfører",
    "regnskapsforer",

    "architect",
    "arkitekt",
]


# Контекст для слишком общих слов.
GENERIC_CONTEXTS = [

    "farm",
    "gård",
    "landbruk",
    "jordbruk",
    "skog",
    "forest",
    "lager",
    "warehouse",
    "produksjon",
    "production",
    "fabrikk",
    "factory",
    "anlegg",
    "construction",
    "dyr",
    "animal",
    "fjøs",
    "fjos",
    "frukt",
    "bær",
    "berry",
    "harvest",
    "sesong",
    "seasonal",
    "ved",
    "wood",
    "tømmer",
    "tommer",
    "traktor",
    "tractor",
    "maskin",
    "machine",
]


# ============================================================
# HELPERS
# ============================================================

def normalize(value):
    """
    Приводим текст к стабильному виду.
    """

    if value is None:
        return ""

    value = str(value)

    value = unicodedata.normalize(
        "NFKC",
        value
    )

    value = value.lower()

    # HTML -> пробелы
    value = re.sub(
        r"<[^>]*>",
        " ",
        value
    )

    # NBSP и прочее
    value = value.replace(
        "\xa0",
        " "
    )

    # Несколько пробелов
    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


def contains_keyword(text, keyword):
    """
    Ищем фразу/слово с более безопасными границами.
    """

    keyword = normalize(keyword)

    if not keyword:
        return False

    if " " in keyword:
        return keyword in text

    return re.search(
        r"(?<![\wåæø])"
        + re.escape(keyword)
        + r"(?![\wåæø])",
        text,
        re.IGNORECASE
    ) is not None


def utc_now():
    return datetime.now(
        timezone.utc
    )


def parse_datetime(value):
    """
    Пытаемся разобрать ISO дату NAV.
    """

    if not value:
        return None

    value = str(value).strip()

    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        dt = datetime.fromisoformat(
            value
        )

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )

    except Exception:
        return None


def rfc1123(dt):
    """
    Формат If-Modified-Since.
    """

    return format_datetime(
        dt.astimezone(timezone.utc),
        usegmt=True
    )


# ============================================================
# HTTP
# ============================================================

def http_request(
    url,
    headers=None,
    retries=MAX_RETRIES
):
    """
    Надёжный GET с retry для временных ошибок.
    """

    last_error = None

    for attempt in range(
        1,
        retries + 1
    ):

        request = urllib.request.Request(
            url,
            headers=headers or {},
            method="GET"
        )

        try:

            with urllib.request.urlopen(
                request,
                timeout=45
            ) as response:

                body = response.read()

                return (
                    response.status,
                    dict(response.headers),
                    body
                )

        except urllib.error.HTTPError as error:

            last_error = error

            status = error.code

            # 304 = ничего нового
            if status == 304:

                return (
                    304,
                    dict(error.headers),
                    b""
                )

            # 429 / 5xx — повторяем
            if status == 429 or status >= 500:

                retry_after = (
                    error.headers.get(
                        "Retry-After"
                    )
                )

                try:
                    wait = float(
                        retry_after
                    )
                except Exception:
                    wait = min(
                        2 ** attempt,
                        30
                    )

                print(
                    f"HTTP {status}. "
                    f"Retry {attempt}/{retries} "
                    f"in {wait:.1f}s..."
                )

                time.sleep(wait)

                continue

            # Остальные HTTP ошибки сразу показываем.
            try:
                error_body = error.read().decode(
                    "utf-8",
                    errors="replace"
                )
            except Exception:
                error_body = ""

            raise RuntimeError(
                f"HTTP {status} for {url}\n"
                f"{error_body[:500]}"
            )

        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError
        ) as error:

            last_error = error

            wait = min(
                2 ** attempt,
                30
            )

            print(
                f"Network error: {error}. "
                f"Retry {attempt}/{retries} "
                f"in {wait}s..."
            )

            time.sleep(wait)

    raise RuntimeError(
        f"Request failed after "
        f"{retries} attempts: {url}\n"
        f"{last_error}"
    )


# ============================================================
# NAV TOKEN
# ============================================================

def get_nav_token():

    print(
        "Getting NAV public token..."
    )

    status, headers, body = http_request(
        NAV_TOKEN_URL,
        {
            "User-Agent": "job-bot/2.0",
            "Accept": "*/*"
        }
    )

    if status != 200:
        raise RuntimeError(
            f"NAV token endpoint returned HTTP {status}"
        )

    text = body.decode(
        "utf-8",
        errors="replace"
    ).strip()

    if not text:
        raise RuntimeError(
            "NAV returned empty token response"
        )

    # NAV может вернуть:
    #
    # *** public token for Nav Job Vacancy Feed:
    # eyJ....eyJ....xxx
    #
    # Нам нужен только JWT.

    matches = re.findall(
        r"(eyJ[A-Za-z0-9_-]+\."
        r"[A-Za-z0-9_-]+\."
        r"[A-Za-z0-9_-]+)",
        text
    )

    if not matches:
        raise RuntimeError(
            "Could not find JWT in NAV token response"
        )

    token = matches[0].strip()

    print(
        "NAV token obtained successfully."
    )

    return token


# ============================================================
# STATE
# ============================================================

def load_json_file(path, default):

    if not os.path.exists(path):
        return default

    try:

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)

    except Exception as error:

        print(
            f"WARNING: could not read {path}: {error}"
        )

        return default


def save_json_file(path, data):

    temporary = path + ".tmp"

    with open(
        temporary,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )

    os.replace(
        temporary,
        path
    )


def get_start_time():

    state = load_json_file(
        STATE_FILE,
        {}
    )

    last_success = state.get(
        "last_successful_sync"
    )

    parsed = parse_datetime(
        last_success
    )

    if parsed:

        start = (
            parsed
            - timedelta(
                minutes=OVERLAP_MINUTES
            )
        )

        print(
            "Incremental sync."
        )

        print(
            "Checking changes since:",
            rfc1123(start)
        )

        return start

    # Первый запуск.
    start = (
        utc_now()
        - timedelta(
            days=INITIAL_LOOKBACK_DAYS
        )
    )

    print(
        "FIRST RUN."
    )

    print(
        "Checking last",
        INITIAL_LOOKBACK_DAYS,
        "days."
    )

    print(
        "Since:",
        rfc1123(start)
    )

    return start


# ============================================================
# FEED
# ============================================================

def get_feed_page(
    url,
    token,
    modified_since
):

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "job-bot/2.0",
        "If-Modified-Since": rfc1123(
            modified_since
        )
    }

    status, response_headers, body = http_request(
        url,
        headers
    )

    if status == 304:
        return (
            None,
            response_headers
        )

    if status != 200:
        raise RuntimeError(
            f"NAV feed returned HTTP {status}"
        )

    try:

        data = json.loads(
            body.decode(
                "utf-8"
            )
        )

    except json.JSONDecodeError as error:

        print(
            body[:1000]
        )

        raise RuntimeError(
            f"Invalid NAV JSON: {error}"
        )

    return (
        data,
        response_headers
    )


# ============================================================
# BASIC MATCH
# ============================================================

def get_basic_text(job):

    feed = job.get(
        "_feed_entry",
        {}
    )

    return normalize(
        " ".join([
            str(job.get("title", "")),
            str(job.get("content_text", "")),
            str(feed.get("title", "")),
            str(feed.get("businessName", "")),
            str(feed.get("municipal", "")),
        ])
    )


def get_title_text(job):

    feed = job.get(
        "_feed_entry",
        {}
    )

    return normalize(
        " ".join([
            str(job.get("title", "")),
            str(feed.get("title", "")),
        ])
    )


def basic_candidate(job):

    title = get_title_text(
        job
    )

    text = get_basic_text(
        job
    )

    # Не отбрасываем по словам из описания.
    # Только TITLE.
    for bad in TITLE_EXCLUDE:

        if contains_keyword(
            title,
            bad
        ):
            return False

    # Сильное совпадение.
    for keyword in STRONG_KEYWORDS:

        if contains_keyword(
            text,
            keyword
        ):
            return True

    # Generic слово разрешаем только
    # при наличии тематического контекста.
    has_generic = any(
        contains_keyword(
            text,
            word
        )
        for word in GENERIC_KEYWORDS
    )

    if has_generic:

        has_context = any(
            contains_keyword(
                text,
                context
            )
            for context in GENERIC_CONTEXTS
        )

        if has_context:
            return True

    return False


# ============================================================
# FULL JOB
# ============================================================

def get_full_job(
    job,
    token
):

    url = job.get(
        "url"
    )

    if not url:
        return None

    url = urllib.parse.urljoin(
        NAV_FEED_URL,
        url
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "job-bot/2.0"
    }

    status, response_headers, body = http_request(
        url,
        headers
    )

    if status != 200:
        return None

    try:

        data = json.loads(
            body.decode(
                "utf-8"
            )
        )

    except Exception:
        return None

    # NAV обычно возвращает:
    # {
    #   uuid,
    #   ad_content,
    #   status
    # }

    status_value = str(
        data.get(
            "status",
            ""
        )
    ).upper()

    if status_value == "INACTIVE":
        return None

    content = data.get(
        "ad_content",
        {}
    )

    if not isinstance(
        content,
        dict
    ):
        content = {}

    return content


# ============================================================
# FULL TEXT / CATEGORY
# ============================================================

def category_text(content):

    parts = []

    occupation_categories = content.get(
        "occupationCategories",
        []
    )

    if isinstance(
        occupation_categories,
        list
    ):

        for item in occupation_categories:

            if isinstance(
                item,
                dict
            ):

                parts.extend([
                    item.get(
                        "level1",
                        ""
                    ),
                    item.get(
                        "level2",
                        ""
                    )
                ])

    category_list = content.get(
        "categoryList",
        []
    )

    if isinstance(
        category_list,
        list
    ):

        for item in category_list:

            if isinstance(
                item,
                dict
            ):

                parts.extend([
                    item.get(
                        "categoryType",
                        ""
                    ),
                    item.get(
                        "name",
                        ""
                    ),
                    item.get(
                        "description",
                        ""
                    )
                ])

    return normalize(
        " ".join(
            str(x)
            for x in parts
            if x
        )
    )


def full_job_matches(
    content
):

    title = normalize(
        content.get(
            "title",
            ""
        )
    )

    jobtitle = normalize(
        content.get(
            "jobtitle",
            ""
        )
    )

    description = normalize(
        content.get(
            "description",
            ""
        )
    )

    categories = category_text(
        content
    )

    combined = " ".join([
        title,
        jobtitle,
        description,
        categories
    ])

    # Отбрасываем только по должности.
    title_for_exclusion = " ".join([
        title,
        jobtitle
    ])

    for bad in TITLE_EXCLUDE:

        if contains_keyword(
            title_for_exclusion,
            bad
        ):
            return False, 0, []

    matched = []

    for keyword in STRONG_KEYWORDS:

        if contains_keyword(
            combined,
            keyword
        ):
            matched.append(
                keyword
            )

    # Generic только с контекстом.
    if not matched:

        generic_found = any(
            contains_keyword(
                combined,
                word
            )
            for word in GENERIC_KEYWORDS
        )

        context_found = any(
            contains_keyword(
                combined,
                context
            )
            for context in GENERIC_CONTEXTS
        )

        if generic_found and context_found:

            matched.append(
                "generic+context"
            )

    if not matched:
        return False, 0, []

    # Вес:
    # title > jobtitle > categories > description
    score = 0

    for keyword in matched:

        if contains_keyword(
            title,
            keyword
        ):
            score += 10

        elif contains_keyword(
            jobtitle,
            keyword
        ):
            score += 9

        elif contains_keyword(
            categories,
            keyword
        ):
            score += 7

        else:
            score += 3

    return True, score, matched


# ============================================================
# FORMAT RESULT
# ============================================================

def build_result(
    feed_job,
    content,
    score,
    matched
):

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
            )
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

    clean_locations = []

    for location in locations:

        if not isinstance(
            location,
            dict
        ):
            continue

        clean_locations.append({
            "country": location.get(
                "country"
            ),
            "county": location.get(
                "county"
            ),
            "municipal": location.get(
                "municipal"
            ),
            "city": location.get(
                "city"
            ),
            "address": location.get(
                "address"
            ),
            "postalCode": location.get(
                "postalCode"
            )
        })

    return {

        "id": feed_job.get(
            "id"
        ),

        "title": (
            content.get(
                "title"
            )
            or feed_job.get(
                "title"
            )
        ),

        "jobtitle": content.get(
            "jobtitle"
        ),

        "company": (
            employer.get(
                "name"
            )
            or feed_job.get(
                "_feed_entry",
                {}
            ).get(
                "businessName"
            )
        ),

        "organization_number":
            employer.get(
                "orgnr"
            ),

        "locations":
            clean_locations,

        "description":
            content.get(
                "description"
            ),

        "application_url":
            content.get(
                "applicationUrl"
            ),

        "source_url":
            content.get(
                "sourceurl"
            ),

        "link":
            content.get(
                "link"
            ),

        "job_url":
            feed_job.get(
                "url"
            ),

        "application_deadline":
            content.get(
                "applicationDue"
            ),

        "start_time":
            content.get(
                "starttime"
            ),

        "employment_type":
            content.get(
                "engagementtype"
            ),

        "extent":
            content.get(
                "extent"
            ),

        "position_count":
            content.get(
                "positioncount"
            ),

        "work_language":
            content.get(
                "workLanguage"
            ),

        "employer_homepage":
            employer.get(
                "homepage"
            ),

        "contacts":
            clean_contacts,

        "matched_keywords":
            matched,

        "score":
            score,

        "date_modified":
            feed_job.get(
                "date_modified"
            ),

        "updated":
            content.get(
                "updated"
            ),

        "published":
            content.get(
                "published"
            ),

        "expires":
            content.get(
                "expires"
            ),
    }


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print("=" * 70)
    print("NORWAY JOB BOT")
    print("=" * 70)

    run_started = utc_now()

    # --------------------------------------------------------
    # TOKEN
    # --------------------------------------------------------

    token = get_nav_token()

    # --------------------------------------------------------
    # STATE
    # --------------------------------------------------------

    state = load_json_file(
        STATE_FILE,
        {}
    )

    jobs_db = load_json_file(
        JOBS_FILE,
        {}
    )

    if not isinstance(
        jobs_db,
        dict
    ):
        jobs_db = {}

    start_time = get_start_time()

    # --------------------------------------------------------
    # STATS
    # --------------------------------------------------------

    pages = 0
    feed_items = 0
    active_items = 0
    inactive_items = 0
    candidates = 0
    details_checked = 0
    matches = 0

    next_url = NAV_FEED_URL

    seen_feed_ids = set()

    # --------------------------------------------------------
    # FEED PAGINATION
    # --------------------------------------------------------

    while next_url:

        pages += 1

        if pages > MAX_PAGES_PER_RUN:

            raise RuntimeError(
                "Safety limit reached: "
                f"{MAX_PAGES_PER_RUN} feed pages. "
                "Increase MAX_PAGES_PER_RUN only "
                "if absolutely necessary."
            )

        print(
            f"Checking feed page {pages}..."
        )

        data, response_headers = get_feed_page(
            next_url,
            token,
            start_time
        )

        # 304 = изменений нет.
        if data is None:

            print(
                "NAV returned 304 - no new changes."
            )

            break

        items = data.get(
            "items",
            []
        )

        print(
            f"Items on page: {len(items)}"
        )

        if not items:

            break

        for job in items:

            feed_items += 1

            job_id = job.get(
                "id"
            )

            if not job_id:
                continue

            if job_id in seen_feed_ids:
                continue

            seen_feed_ids.add(
                job_id
            )

            feed = job.get(
                "_feed_entry",
                {}
            )

            status = str(
                feed.get(
                    "status",
                    ""
                )
            ).upper()

            # ------------------------------------------------
            # INACTIVE
            # ------------------------------------------------

            if status != "ACTIVE":

                inactive_items += 1

                # Если раньше сохраняли вакансию —
                # удаляем её.
                jobs_db.pop(
                    job_id,
                    None
                )

                continue

            active_items += 1

            # ------------------------------------------------
            # BASIC FILTER
            # ------------------------------------------------

            if not basic_candidate(
                job
            ):
                continue

            candidates += 1

            # ------------------------------------------------
            # FULL DETAILS
            # ------------------------------------------------

            details_checked += 1

            time.sleep(
                REQUEST_DELAY
            )

            content = get_full_job(
                job,
                token
            )

            # Важная проверка:
            # статус мог измениться между feed
            # и detail request.
            if content is None:

                jobs_db.pop(
                    job_id,
                    None
                )

                continue

            is_match, score, matched = (
                full_job_matches(
                    content
                )
            )

            if not is_match:

                # Вакансия раньше могла подходить,
                # но после изменения больше не подходит.
                jobs_db.pop(
                    job_id,
                    None
                )

                continue

            matches += 1

            result = build_result(
                job,
                content,
                score,
                matched
            )

            jobs_db[job_id] = result

            print(
                "MATCH:",
                result.get(
                    "title"
                ),
                "|",
                result.get(
                    "company"
                ),
                "| score:",
                score
            )

        # ----------------------------------------------------
        # NEXT PAGE
        # ----------------------------------------------------

        next_url = data.get(
            "next_url"
        )

        if next_url:

            next_url = urllib.parse.urljoin(
                NAV_FEED_URL,
                next_url
            )

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    sorted_jobs = sorted(
        jobs_db.values(),
        key=lambda job: (
            job.get(
                "score",
                0
            ),
            job.get(
                "date_modified",
                ""
            )
        ),
        reverse=True
    )

    # --------------------------------------------------------
    # SAVE JOBS
    # --------------------------------------------------------

    output = {

        "generated_at":
            utc_now().isoformat(),

        "total_matching_jobs":
            len(sorted_jobs),

        "jobs":
            sorted_jobs
    }

    save_json_file(
        JOBS_FILE,
        output
    )

    # --------------------------------------------------------
    # SAVE STATE
    # --------------------------------------------------------

    new_state = {

        "last_successful_sync":
            run_started.isoformat(),

        "last_completed_at":
            utc_now().isoformat(),

        "feed_pages":
            pages,

        "feed_items":
            feed_items,

        "active_items":
            active_items,

        "inactive_items":
            inactive_items,

        "candidates":
            candidates,

        "details_checked":
            details_checked,

        "matches_found_this_run":
            matches,

        "total_saved_matching_jobs":
            len(sorted_jobs)
    }

    save_json_file(
        STATE_FILE,
        new_state
    )

    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    print("")
    print("=" * 70)
    print("SYNC FINISHED")
    print("=" * 70)

    print(
        "Feed pages:",
        pages
    )

    print(
        "Feed items:",
        feed_items
    )

    print(
        "Active items:",
        active_items
    )

    print(
        "Inactive items:",
        inactive_items
    )

    print(
        "Candidates:",
        candidates
    )

    print(
        "Details checked:",
        details_checked
    )

    print(
        "Matches this run:",
        matches
    )

    print(
        "Total saved matching jobs:",
        len(sorted_jobs)
    )

    print("=" * 70)

    # --------------------------------------------------------
    # SHOW TOP JOBS
    # --------------------------------------------------------

    for number, job in enumerate(
        sorted_jobs[:30],
        start=1
    ):

        print("")
        print(
            f"#{number}",
            job.get(
                "title"
            )
        )

        print(
            "Company:",
            job.get(
                "company"
            )
        )

        print(
            "Score:",
            job.get(
                "score"
            )
        )

        print(
            "Keywords:",
            ", ".join(
                job.get(
                    "matched_keywords",
                    []
                )
            )
        )

        print(
            "Apply:",
            job.get(
                "application_url"
            )
        )

        print(
            "Job:",
            job.get(
                "job_url"
            )
        )

        for contact in job.get(
            "contacts",
            []
        ):

            email = contact.get(
                "email"
            )

            phone = contact.get(
                "phone"
            )

            if email:
                print(
                    "Email:",
                    email
                )

            if phone:
                print(
                    "Phone:",
                    phone
                )

    print("")
    print("=" * 70)
    print("JOB BOT FINISHED SUCCESSFULLY")
    print("=" * 70)


if __name__ == "__main__":
    main()
