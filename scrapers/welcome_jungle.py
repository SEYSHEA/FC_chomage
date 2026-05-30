import logging
import time
import urllib.parse
import requests
from .base import BaseScraper, Job

log = logging.getLogger(__name__)

# Public Algolia credentials embedded in WTTJ's own frontend JS
ALGOLIA_URL    = "https://csekhvms53-1.algolianet.com/1/indexes/*/queries"
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

CITY_COORDS = {
    "paris":            (48.8566,  2.3522),
    "nice":             (43.7102,  7.2620),
    "marseille":        (43.2965,  5.3698),
    "lyon":             (45.7640,  4.8357),
    "bordeaux":         (44.8378, -0.5792),
    "toulouse":         (43.6047,  1.4442),
    "lille":            (50.6292,  3.0573),
    "sophia antipolis": (43.6167,  7.0500),
    "aix-en-provence":  (43.5297,  5.4474),
    "remote":           (48.8566,  2.3522),
}


def _get_coords(location: str) -> tuple[float, float]:
    return CITY_COORDS.get(location.lower().split(",")[0].strip(), (48.8566, 2.3522))


def _safe_get(obj, *keys, default=""):
    """Traverse nested dicts safely; returns default if any level is not a dict."""
    for k in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k, default)
    return obj if obj is not None else default


def _build_params_str(keyword: str, contract_codes: list[str], location: str, rayon_km: int) -> str:
    lat, lng = _get_coords(location)
    # urllib.parse.urlencode handles spaces and special chars properly
    params = {
        "query":        keyword,
        "aroundLatLng": f"{lat},{lng}",
        "aroundRadius": rayon_km * 1000,
        "hitsPerPage":  50,
        "page":         0,
    }
    if contract_codes:
        ct_filter = " OR ".join(f'contract_type:"{c}"' for c in contract_codes)
        params["filters"] = f"({ct_filter})"

    return urllib.parse.urlencode(params)


def _parse_hit(hit: dict) -> Job | None:
    if not isinstance(hit, dict):
        return None

    title = hit.get("name") or ""
    if not title:
        return None

    # organization peut être un dict OU absent si Algolia renvoie les champs à plat
    org = hit.get("organization")
    if isinstance(org, dict):
        company  = org.get("name") or "Entreprise non précisée"
        org_slug = org.get("slug") or ""
    else:
        company  = str(org) if org else "Entreprise non précisée"
        org_slug = ""

    job_slug = hit.get("slug") or ""
    ref      = hit.get("reference") or ""

    if org_slug and job_slug:
        url = f"https://www.welcometothejungle.com/fr/companies/{org_slug}/jobs/{job_slug}"
        if ref:
            url += f"?q={ref}"
    else:
        return None

    # offices est une liste de dicts, mais chaque élément peut varier
    offices     = hit.get("offices") or []
    first_off   = offices[0] if offices else {}
    if isinstance(first_off, dict):
        city        = first_off.get("city") or ""
        country_raw = first_off.get("country")
        country     = _safe_get(country_raw, "name", default="France") if isinstance(country_raw, dict) else (str(country_raw) if country_raw else "France")
    else:
        city    = str(first_off) if first_off else ""
        country = "France"
    loc_str = f"{city}, {country}" if city else "France"

    contract = hit.get("contract_type") or ""

    sal_min  = hit.get("salary_yearly_minimum")
    sal_max  = hit.get("salary_yearly_maximum")
    currency = hit.get("salary_currency") or "€"
    salary   = ""
    try:
        if sal_min and sal_max:
            salary = f"{int(sal_min):,} – {int(sal_max):,} {currency}/an"
        elif sal_min:
            salary = f"À partir de {int(sal_min):,} {currency}/an"
    except (ValueError, TypeError):
        pass

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
        rayon_km       = self.config.get("localisation", {}).get("rayon_km", 50)

        for i, keyword in enumerate(keywords[:8]):
            if len(jobs) >= self.max_results:
                break
            if i > 0:
                time.sleep(1)

            params_str = _build_params_str(keyword, contract_codes, location, rayon_km)
            payload    = {"requests": [{"indexName": INDEX_NAME, "params": params_str}]}

            try:
                resp = self._session.post(ALGOLIA_URL, json=payload, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                log.warning(f"Welcome to the Jungle erreur pour '{keyword}' ({location}): {e}")
                continue

            if not isinstance(data, dict):
                log.warning(f"Welcome to the Jungle: réponse inattendue ({type(data).__name__}) pour '{keyword}'")
                continue

            results = data.get("results")
            if not isinstance(results, list) or not results:
                log.debug(f"Welcome to the Jungle: pas de results pour '{keyword}'. Réponse: {data}")
                continue

            hits = results[0].get("hits") if isinstance(results[0], dict) else []
            for hit in (hits or [])[: self.max_results]:
                job = _parse_hit(hit)
                if job and job.url not in seen_urls:
                    seen_urls.add(job.url)
                    jobs.append(job)

        return jobs
