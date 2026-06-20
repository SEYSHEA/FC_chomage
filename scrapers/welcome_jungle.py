import logging
import re
import time
import requests
from .base import BaseScraper, Job

log = logging.getLogger(__name__)

BASE         = "https://www.welcometothejungle.com"
HOME_URL     = f"{BASE}/fr/jobs"

# Credentials publics embarqués dans le JS de WTTJ (extraits dynamiquement, sinon fallback)
FALLBACK_APP_ID  = "CSEKHVMS53"
FALLBACK_API_KEY = "0f169f7e79e0d2f8c8f1e5b7a3f7a9e4"
FALLBACK_INDEX   = "wttj_jobs_production_fr"

HEADERS = {
    "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept":       "application/json",
    "Content-Type": "application/json",
    "Referer":      BASE,
    "Origin":       BASE,
}

CONTRACT_MAP = {
    "CDI":        "FULL_TIME",
    "CDD":        "TEMPORARY",
    "Stage":      "INTERNSHIP",
    "Alternance": "APPRENTICESHIP",
    "Freelance":  "FREELANCE",
    "Intérim":    "INTERIM",
}

# Filtres Algolia par zone (utilise les champs natifs de l'index WTTJ)
ZONE_FILTERS = {
    "paris":     'offices.state:"Ile-de-France"',
    "nice":      'offices.department_code:"06"',
    "marseille": 'offices.department_code:"13"',
    "remote":    'remote:"fulltime"',
}


def _fetch_credentials(session: requests.Session) -> tuple[str, str, str]:
    """Extrait les credentials Algolia depuis window.env dans le HTML de WTTJ."""
    try:
        resp = session.get(HOME_URL, timeout=15)
        if resp.ok:
            m = re.search(r'window\.env\s*=\s*(\{[^<]+?\})', resp.text, re.DOTALL)
            if m:
                env_str = m.group(1)
                app_id  = re.search(r'"ALGOLIA_APPLICATION_ID"\s*:\s*"([^"]+)"', env_str)
                api_key = re.search(r'"ALGOLIA_API_KEY_CLIENT"\s*:\s*"([^"]+)"', env_str)
                index   = re.search(r'"ALGOLIA_JOBS_INDEX_PREFIX"\s*:\s*"([^"]+)"', env_str)
                if app_id and api_key and index:
                    idx = index.group(1)
                    if not idx.endswith("_fr"):
                        idx += "_fr"
                    log.debug(f"WTTJ: credentials extraits dynamiquement (app_id={app_id.group(1)})")
                    return app_id.group(1), api_key.group(1), idx
    except Exception:
        pass
    log.debug("WTTJ: utilisation des credentials de fallback")
    return FALLBACK_APP_ID, FALLBACK_API_KEY, FALLBACK_INDEX


def _build_filter(contract_codes: list[str], location: str) -> str:
    parts = ["offices.country_code:FR"]
    zone_f = ZONE_FILTERS.get(location.lower().split(",")[0].strip())
    if zone_f and location.lower() != "remote":
        parts.append(zone_f)
    if contract_codes:
        ct = " OR ".join(f'contract_type:"{c}"' for c in contract_codes)
        parts.append(f"({ct})")
    return " AND ".join(parts)


def _parse_hit(hit: dict) -> Job | None:
    title = hit.get("name") or hit.get("title") or ""
    if not title:
        return None

    org = hit.get("organization") or {}
    company = (org.get("name") if isinstance(org, dict) else str(org)) or "Entreprise non précisée"
    org_slug = (org.get("slug") if isinstance(org, dict) else "") or ""
    job_slug = hit.get("slug") or ""

    # URL : deux formats possibles selon l'index
    if org_slug and job_slug:
        url = f"{BASE}/fr/companies/{org_slug}/jobs/{job_slug}"
    elif job_slug:
        url = f"{BASE}/fr/jobs/{job_slug}"
    else:
        return None

    # Localisation — offices peut être liste ou dict
    offices = hit.get("offices") or hit.get("office") or [{}]
    if isinstance(offices, dict):
        offices = [offices]
    first = offices[0] if offices else {}
    city    = (first.get("city") if isinstance(first, dict) else "") or ""
    country = ""
    if isinstance(first, dict):
        c = first.get("country")
        country = (c.get("name") if isinstance(c, dict) else str(c)) if c else "France"
    loc_str = f"{city}, {country}".strip(", ") or "France"

    contract = hit.get("contract_type") or ""

    sal_min  = hit.get("salary_yearly_minimum") or hit.get("salary_minimum")
    sal_max  = hit.get("salary_yearly_maximum") or hit.get("salary_maximum")
    currency = hit.get("salary_currency") or "€"
    salary   = ""
    try:
        if sal_min and sal_max:
            salary = f"{int(sal_min):,} – {int(sal_max):,} {currency}/an"
        elif sal_min:
            salary = f"À partir de {int(sal_min):,} {currency}/an"
    except (ValueError, TypeError):
        pass

    desc = str(hit.get("summary") or hit.get("key_missions") or hit.get("description") or "")[:500]
    date = str(hit.get("published_at") or "")[:10]

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
        self._app_id  = ""
        self._api_key = ""
        self._index   = ""

    def _ensure_credentials(self):
        if not self._app_id:
            self._app_id, self._api_key, self._index = _fetch_credentials(self._session)
            self._session.headers["X-Algolia-Application-Id"] = self._app_id
            self._session.headers["X-Algolia-API-Key"]        = self._api_key

    def search(self, keywords: list[str], location: str) -> list[Job]:
        self._ensure_credentials()

        jobs: list[Job] = []
        seen_urls: set[str] = set()

        contract_types = self.config.get("contrat", {}).get("types", [])
        contract_codes = [CONTRACT_MAP[c] for c in contract_types if c in CONTRACT_MAP]
        algolia_filter = _build_filter(contract_codes, location)

        api_url = f"https://{self._app_id}-dsn.algolia.net/1/indexes/{self._index}/query"

        for i, keyword in enumerate(keywords[:8]):
            if len(jobs) >= self.max_results:
                break
            if i > 0:
                time.sleep(1)

            body = {
                "query":               keyword,
                "hitsPerPage":         min(50, self.max_results),
                "page":                0,
                "filters":             algolia_filter,
                "attributesToRetrieve": [
                    "name", "slug", "organization", "offices", "office",
                    "published_at", "contract_type", "salary_yearly_minimum",
                    "salary_yearly_maximum", "salary_currency", "summary",
                    "key_missions", "description",
                ],
            }

            try:
                resp = self._session.post(api_url, json=body, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                log.warning(f"Welcome to the Jungle erreur pour '{keyword}' ({location}): {e}")
                continue

            if not isinstance(data, dict):
                log.warning(f"WTTJ: réponse inattendue ({type(data).__name__})")
                continue

            for hit in (data.get("hits") or [])[: self.max_results]:
                job = _parse_hit(hit)
                if job and job.url not in seen_urls:
                    seen_urls.add(job.url)
                    jobs.append(job)

        return jobs
