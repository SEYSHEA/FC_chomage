import json
import logging
import re
import requests
from .base import BaseScraper, Job

log = logging.getLogger(__name__)

BASE = "https://www.welcometothejungle.com"
SEARCH_URL = f"{BASE}/fr/jobs"

CONTRACT_MAP = {
    "CDI":        "permanent",
    "CDD":        "temporary",
    "Stage":      "internship",
    "Alternance": "apprenticeship",
    "Freelance":  "freelance",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Referer": f"{BASE}/fr/jobs",
}


def _build_params(keyword: str, contract_types: list[str], include_remote: bool) -> dict:
    params = {
        "query": keyword,
        "page": 1,
    }
    wtj_contracts = [CONTRACT_MAP[c] for c in contract_types if c in CONTRACT_MAP]
    if wtj_contracts:
        params["contract_type[]"] = wtj_contracts
    if include_remote:
        params["remote[]"] = "fulltime"
    return params


def _extract_jobs_from_next_data(raw_json: dict) -> list[dict]:
    """Dig into __NEXT_DATA__ to find the jobs array."""
    try:
        # Path varies by WTTJ version; try several
        props = raw_json.get("props", {})
        page_props = props.get("pageProps", {})

        # Pattern 1 : pageProps.jobs
        jobs = page_props.get("jobs")
        if isinstance(jobs, list) and jobs:
            return jobs

        # Pattern 2 : pageProps.searchResults.jobs
        jobs = page_props.get("searchResults", {}).get("jobs")
        if isinstance(jobs, list) and jobs:
            return jobs

        # Pattern 3 : pageProps.initialState.jobs.list
        jobs = (
            page_props.get("initialState", {})
            .get("jobs", {})
            .get("list")
        )
        if isinstance(jobs, list) and jobs:
            return jobs

        # Pattern 4 : dehydratedState queries
        for query in page_props.get("dehydratedState", {}).get("queries", []):
            data = query.get("state", {}).get("data", {})
            if isinstance(data, dict):
                jobs = data.get("jobs") or data.get("results") or data.get("data")
                if isinstance(jobs, list) and jobs:
                    return jobs

    except Exception:
        pass
    return []


def _parse_job(item: dict, location: str) -> Job | None:
    title = item.get("name") or item.get("title") or ""
    if not title:
        return None

    org = item.get("organization") or {}
    company = org.get("name") or item.get("company_name") or "Entreprise non précisée"

    org_slug = org.get("slug") or item.get("organization_slug") or ""
    job_slug = item.get("slug") or ""
    ref = item.get("reference") or ""

    if org_slug and job_slug:
        url = f"{BASE}/fr/companies/{org_slug}/jobs/{job_slug}"
        if ref:
            url += f"?q={ref}"
    else:
        url = item.get("url") or item.get("apply_url") or ""
    if not url:
        return None

    office = item.get("office") or {}
    city = office.get("city") or item.get("city") or location
    country = (office.get("country") or {}).get("name_fr") or "France"
    loc_str = f"{city}, {country}" if city else location

    contract = (item.get("contract_type") or {}).get("name") or {}
    contract_label = (
        contract.get("fr") if isinstance(contract, dict) else str(contract)
    )

    salary_min = item.get("salary_minimum")
    salary_max = item.get("salary_maximum")
    currency = item.get("salary_currency", "€")
    salary_str = ""
    if salary_min and salary_max:
        salary_str = f"{salary_min:,} – {salary_max:,} {currency}/an"
    elif salary_min:
        salary_str = f"À partir de {salary_min:,} {currency}/an"

    return Job(
        title=str(title),
        company=str(company),
        location=loc_str,
        url=url,
        platform="Welcome to the Jungle",
        contract_type=str(contract_label or ""),
        salary=salary_str,
        description=str(item.get("description", ""))[:500],
        date_posted=str(item.get("published_at", ""))[:10],
    )


class WelcomeJungleScraper(BaseScraper):
    name = "Welcome to the Jungle"

    def __init__(self, config: dict):
        super().__init__(config)
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def search(self, keywords: list[str], location: str) -> list[Job]:
        jobs: list[Job] = []
        seen_urls: set[str] = set()

        cfg = self.config
        contract_types = cfg.get("contrat", {}).get("types", [])
        include_remote = cfg.get("localisation", {}).get("inclure_remote", True)

        for keyword in keywords[:8]:
            if len(jobs) >= self.max_results:
                break

            params = _build_params(keyword, contract_types, include_remote)

            try:
                resp = self._session.get(SEARCH_URL, params=params, timeout=25)
                resp.raise_for_status()
            except Exception as e:
                log.warning(f"Welcome to the Jungle erreur pour '{keyword}': {e}")
                continue

            # Extract __NEXT_DATA__ embedded JSON
            match = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
                resp.text,
                re.DOTALL,
            )
            if not match:
                log.warning(
                    f"Welcome to the Jungle: __NEXT_DATA__ introuvable pour '{keyword}'. "
                    "Le site a peut-être changé de structure."
                )
                continue

            try:
                next_data = json.loads(match.group(1))
            except json.JSONDecodeError:
                log.warning(f"Welcome to the Jungle: JSON invalide pour '{keyword}'")
                continue

            raw_jobs = _extract_jobs_from_next_data(next_data)
            if not raw_jobs:
                log.debug(
                    f"Welcome to the Jungle: aucune offre dans __NEXT_DATA__ pour '{keyword}'. "
                    f"Clés disponibles: {list((next_data.get('props') or {}).get('pageProps', {}).keys())}"
                )

            for item in raw_jobs[: self.max_results]:
                job = _parse_job(item, location)
                if job and job.url not in seen_urls:
                    seen_urls.add(job.url)
                    jobs.append(job)

        return jobs
