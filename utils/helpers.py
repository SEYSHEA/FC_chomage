import re
from scrapers.base import Job


def normalize(text: str) -> str:
    """Lowercase and strip accents for flexible matching."""
    text = text.lower()
    replacements = {
        "é": "e", "è": "e", "ê": "e", "ë": "e",
        "à": "a", "â": "a", "ä": "a",
        "î": "i", "ï": "i",
        "ô": "o", "ö": "o",
        "ù": "u", "û": "u", "ü": "u",
        "ç": "c",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def calculate_relevance(job: Job, keywords: list[str], exclude_keywords: list[str]) -> float:
    """
    Score a job by keyword relevance.
    Title matches count double. Exclusion keywords apply a large penalty.
    """
    title_text = normalize(job.title)
    body_text = normalize(f"{job.description} {job.company} {job.location}")

    score = 0.0

    for kw in keywords:
        kw_norm = normalize(kw)
        if kw_norm in title_text:
            score += 3.0
        elif kw_norm in body_text:
            score += 1.0

    for ex_kw in exclude_keywords:
        ex_norm = normalize(ex_kw)
        if ex_norm in title_text or ex_norm in body_text:
            score -= 10.0

    return score


def _matches_keyword(job: Job, keywords: list[str]) -> bool:
    combined = normalize(f"{job.title} {job.description}")
    return any(normalize(kw) in combined for kw in keywords)


def _matches_contract(job: Job, desired_types: list[str]) -> bool:
    if not desired_types:
        return True
    if not job.contract_type:
        return True     # Unknown contract: include by default

    job_contract = normalize(job.contract_type)
    for ct in desired_types:
        if normalize(ct) in job_contract:
            return True
    return False


def _exceeds_min_salary(job: Job, min_salary: int, show_no_salary: bool) -> bool:
    if min_salary <= 0:
        return True
    if not job.salary:
        return show_no_salary

    # Try to extract first number from salary string
    numbers = re.findall(r"\d[\d\s]*\d|\d+", job.salary.replace(" ", "").replace(" ", ""))
    if not numbers:
        return show_no_salary
    try:
        first_num = int(numbers[0])
        # If the number looks like monthly (< 10000), convert to annual
        if first_num < 10_000:
            first_num *= 12
        return first_num >= min_salary
    except ValueError:
        return show_no_salary


def _is_remote_or_local(job: Job, city: str, include_remote: bool) -> bool:
    loc = normalize(job.location)
    city_norm = normalize(city)

    # Correspondances régionales étendues
    REGIONAL = {
        "paris":     ["paris", "ile-de-france", "idf", "75", "92", "93", "94", "hauts-de-seine",
                      "seine-saint-denis", "val-de-marne", "versailles", "boulogne", "la defense",
                      "saint-denis", "creteil", "nanterre"],
        "nice":      ["nice", "alpes-maritimes", "cote d'azur", "cote d azur", "06", "grasse",
                      "sophia antipolis", "antibes", "cannes", "menton", "biot", "valbonne"],
        "marseille": ["marseille", "bouches-du-rhone", "13", "aix-en-provence", "aix en provence",
                      "aubagne", "martigues"],
    }

    synonyms = REGIONAL.get(city_norm, [city_norm])
    if any(s in loc for s in synonyms):
        return True

    remote_keywords = ["remote", "teletravail", "tele-travail", "a distance", "full remote",
                       "100% remote", "full-remote"]
    if include_remote and any(rk in loc for rk in remote_keywords):
        return True

    # Localisation vide ou générique → on garde
    if not job.location.strip() or job.location.strip() in ("France", "FR"):
        return True

    return False


def filter_jobs(
    jobs: list[Job],
    keywords: list[str],
    exclude_keywords: list[str],
    contract_types: list[str],
    min_salary: int,
    show_no_salary: bool,
    include_remote: bool,
    city: str = "",
) -> list[Job]:
    """Filter a list of jobs against all user criteria."""
    result = []
    for job in jobs:
        # Must match at least one keyword
        if not _matches_keyword(job, keywords):
            continue
        # Must not match exclusion keywords
        if exclude_keywords:
            ex_norm = normalize(" ".join(exclude_keywords))
            combined = normalize(f"{job.title} {job.description}")
            if any(normalize(ex) in combined for ex in exclude_keywords):
                continue
        # Contract type filter
        if not _matches_contract(job, contract_types):
            continue
        # Salary filter
        if not _exceeds_min_salary(job, min_salary, show_no_salary):
            continue
        # Location filter — exclut les postes à l'étranger
        if city and not _is_remote_or_local(job, city, include_remote):
            continue
        result.append(job)
    return result
