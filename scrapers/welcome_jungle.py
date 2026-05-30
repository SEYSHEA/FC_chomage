import logging
import time
import requests
from .base import BaseScraper, Job

log = logging.getLogger(__name__)

# Public Algolia credentials embedded in WTTJ's own frontend JS
ALGOLIA_URL    = "https://csekhvms53-dsn.algolia.net/1/indexes/*/queries"
ALGOLIA_APP_ID = "CSEKHVMS53"
ALGOLIA_KEY    = "4bd8f6215d0cc52b26430765769e65a0"
INDEX_NAME     = "wttj_jobs_production_fr"

HEADERS = {
    "x-algolia-application-id": ALGOLIA_APP_ID,
    "x-algolia-api-key":        ALGOLIA_KEY,
    "Content-Type":             "application/json",
    "Referer":                  "https://www.welcometothejungle.com/",
    "User-Agent":               "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/144.0",
}

CONTRACT_MAP = {
    "CDI":        "FULL_TIME",
    "CDD":        "TEMPORARY",
    "Stage":      "INTERNSHIP",
    "Alternance": "APPRENTICESHIP",
    "Freelance":  "FREELANCE",
}

ATTRS = ",".join([
    "name", "organization.name", "organization.slug", "slug",
    "contract_type", "salary_yearly_minimum", "salary_yearly_maximum",
    "salary_currency", "offices", "published_at", "reference", "remote",
    "experience_level_minimum", "description",
])


def _build_params_str(keyword: str, contract_codes: list[str], location: str) -> str:
    filters = ['offices.country_code:"FR"']
    if contract_codes:
        ct_filter = " OR ".join(f'contract_type:"{c}"' for c in contract_codes)
        filters.append(f"({ct_filter})")

    parts = [
        f"query={keyword}",
        f"filters={' AND '.join(filters)}",
        "hitsPerPage=50",
        "page=0",
        f"attributesToRetrieve=[{ATTRS}]",
        "responseFields=[hits,nbHits,nbPages,page]",
    ]
    return "&".join(parts)


def _parse_hit(hit: dict) -> Job | None:
    title = hit.get("name") or ""
    if not title:
        return None

    org        = hit.get("organization") or {}
    company    = org.get("name") or "Entreprise non précisée"
    org_slug   = org.get("slug") or ""
    job_slug   = hit.get("slug") or ""
    ref        = hit.get("reference") or ""

    if org_slug and job_slug:
        url = f"https://www.welcometothejungle.com/fr/companies/{org_slug}/jobs/{job_slug}"
        if ref:
            url += f"?q={ref}"
    else:
        return None

    offices = hit.get("offices") or [{}]
    city    = offices[0].get("city") or ""
    country = (offices[0].get("country") or {}).get("name") or "France"
    loc_str = f"{city}, {country}" if city else "France"

    contract = hit.get("contract_type") or ""

    sal_min  = hit.get("salary_yearly_minimum")
    sal_max  = hit.get("salary_yearly_maximum")
    currency = hit.get("salary_currency") or "€"
    salary   = ""
    if sal_min and sal_max:
        salary = f"{int(sal_min):,} – {int(sal_max):,} {currency}/an"
    elif sal_min:
        salary = f"À partir de {int(sal_min):,} {currency}/an"

    date = str(hit.get("published_at") or "")[:10]
    desc = str(hit.get("description") or "")[:500]

    return Job(
        title=str(title),
        company=str(company),
        location=loc_str,
        url=url,
        platform="Welcome to the Jungle",
        contract_type=str(contract),
        salary=salary,
        description=desc,
        date_posted=date,
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

        contract_types = self.config.get("contrat", {}).get("types", [])
        contract_codes = [CONTRACT_MAP[c] for c in contract_types if c in CONTRACT_MAP]

        for i, keyword in enumerate(keywords[:8]):
            if len(jobs) >= self.max_results:
                break

            if i > 0:
                time.sleep(1)

            params_str = _build_params_str(keyword, contract_codes, location)
            payload = {"requests": [{"indexName": INDEX_NAME, "params": params_str}]}

            try:
                resp = self._session.post(ALGOLIA_URL, json=payload, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                log.warning(f"Welcome to the Jungle erreur pour '{keyword}': {e}")
                continue

            hits = (data.get("results") or [{}])[0].get("hits") or []
            for hit in hits[: self.max_results]:
                job = _parse_hit(hit)
                if job and job.url not in seen_urls:
                    seen_urls.add(job.url)
                    jobs.append(job)

        return jobs
