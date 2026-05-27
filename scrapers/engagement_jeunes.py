import logging
import re
import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, Job

log = logging.getLogger(__name__)

BASE_URL = "https://www.engagement-jeunes.com"

# Candidats d'endpoints API à essayer dans l'ordre
API_CANDIDATES = [
    f"{BASE_URL}/api/offres",
    f"{BASE_URL}/api/v1/offres",
    f"{BASE_URL}/api/jobs",
    f"{BASE_URL}/api/v1/jobs",
    f"{BASE_URL}/api/missions",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Referer": f"{BASE_URL}/fr/dashboard.html",
    "Origin": BASE_URL,
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_text(obj, *keys, default=""):
    """Safely dig into a nested dict: _extract_text(d, 'a', 'b', 'c')."""
    for k in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k, default)
    return obj if obj else default


def _parse_json_offer(item: dict, platform: str) -> Job | None:
    """Convert a raw JSON offer dict to a Job object.
    Tries multiple common field name patterns."""

    # Title
    title = (
        item.get("titre")
        or item.get("title")
        or item.get("intitule")
        or item.get("poste")
        or item.get("nom")
        or ""
    )
    if not title:
        return None

    # Company / organisation
    company = (
        item.get("organisation")
        or item.get("structure")
        or item.get("entreprise")
        or item.get("company")
        or _extract_text(item, "organisation", "nom")
        or _extract_text(item, "structure", "nom")
        or "Structure non précisée"
    )

    # Location
    location = (
        item.get("ville")
        or item.get("lieu")
        or item.get("location")
        or item.get("localisation")
        or _extract_text(item, "lieu", "libelle")
        or ""
    )

    # URL
    slug = item.get("slug") or item.get("id") or item.get("_id") or ""
    url = (
        item.get("url")
        or item.get("lien")
        or item.get("link")
        or (f"{BASE_URL}/fr/offre/{slug}" if slug else "")
    )
    if not url:
        return None

    # Contract type
    contract = (
        item.get("type_contrat")
        or item.get("typeContrat")
        or item.get("contract_type")
        or item.get("type")
        or ""
    )

    # Salary
    salary = (
        item.get("salaire")
        or item.get("remuneration")
        or item.get("salary")
        or ""
    )

    # Description
    desc = (
        item.get("description")
        or item.get("description_courte")
        or item.get("summary")
        or ""
    )

    # Date
    date = (
        item.get("date_publication")
        or item.get("datePublication")
        or item.get("published_at")
        or item.get("created_at")
        or ""
    )

    return Job(
        title=str(title),
        company=str(company),
        location=str(location),
        url=str(url),
        platform=platform,
        contract_type=str(contract),
        salary=str(salary),
        description=str(desc)[:500],
        date_posted=str(date)[:10],
    )


# ── Main scraper ──────────────────────────────────────────────────────────────

class EngagementJeunesScraper(BaseScraper):
    name = "Engagement Jeunes"

    def __init__(self, config: dict):
        super().__init__(config)
        ej_cfg = config.get("plateformes", {}).get("engagement_jeunes", {})
        # Allow user to set the exact API endpoint after discovery (see README)
        self._custom_api_url: str = ej_cfg.get("api_url", "").strip()
        self._session = requests.Session()
        self._session.headers.update(HEADERS)
        self._discovered_url: str = ""

    def _discover_api_url(self) -> str:
        """
        Try to find the working API endpoint either from config or by probing.
        Returns the working URL or empty string.
        """
        if self._custom_api_url:
            return self._custom_api_url
        if self._discovered_url:
            return self._discovered_url

        # Strategy 1 : scan the main page JS bundle for the API base URL
        try:
            resp = self._session.get(f"{BASE_URL}/fr/dashboard.html", timeout=15)
            if resp.ok:
                # Look for API URL patterns embedded in scripts
                matches = re.findall(
                    r'(?:apiUrl|API_URL|baseURL|api_base)["\s:=]+["\']([^"\']+)["\']',
                    resp.text,
                )
                for m in matches:
                    if m.startswith("http"):
                        log.debug(f"Engagement Jeunes: API URL candidate from JS: {m}")
        except Exception:
            pass

        # Strategy 2 : probe known patterns
        for candidate in API_CANDIDATES:
            try:
                probe = self._session.get(
                    candidate,
                    params={"page": 1, "limit": 1},
                    timeout=10,
                )
                if probe.ok and probe.headers.get("Content-Type", "").startswith("application/json"):
                    log.info(f"Engagement Jeunes: endpoint trouvé → {candidate}")
                    self._discovered_url = candidate
                    return candidate
            except Exception:
                continue

        return ""

    def _search_via_api(self, keyword: str, location: str, api_url: str) -> list[Job]:
        jobs: list[Job] = []

        # Common query parameter patterns
        param_variants = [
            {"q": keyword, "ville": location, "page": 1, "limit": self.max_results},
            {"keywords": keyword, "location": location, "page": 1, "per_page": self.max_results},
            {"mots_cles": keyword, "localisation": location, "page": 1},
            {"search": keyword, "lieu": location, "page": 1},
            {"q": keyword, "page": 1},
        ]

        data = None
        for params in param_variants:
            try:
                resp = self._session.get(api_url, params=params, timeout=20)
                if resp.ok:
                    data = resp.json()
                    break
            except Exception:
                continue

        if data is None:
            return jobs

        # Unwrap common response envelopes
        items = (
            data if isinstance(data, list)
            else data.get("offres")
            or data.get("results")
            or data.get("jobs")
            or data.get("data")
            or data.get("items")
            or []
        )

        for item in items[: self.max_results]:
            job = _parse_json_offer(item, self.name)
            if job:
                jobs.append(job)

        return jobs

    def _search_via_html(self, keyword: str, location: str) -> list[Job]:
        """Fallback: parse the search results HTML page."""
        jobs: list[Job] = []

        search_urls = [
            f"{BASE_URL}/fr/offres?q={keyword}&lieu={location}",
            f"{BASE_URL}/fr/dashboard.html#/offres?q={keyword}",
            f"{BASE_URL}/fr/missions?q={keyword}&lieu={location}",
        ]

        html = ""
        for url in search_urls:
            try:
                resp = self._session.get(url, timeout=20)
                if resp.ok and len(resp.text) > 500:
                    html = resp.text
                    break
            except Exception:
                continue

        if not html:
            return jobs

        soup = BeautifulSoup(html, "html.parser")

        # Look for common job card selectors
        selectors = [
            "article.offre", "div.offre", ".job-card", ".mission-card",
            "li.offre", "[data-offre]", ".result-item", "article",
        ]
        cards = []
        for sel in selectors:
            cards = soup.select(sel)
            if len(cards) > 1:
                break

        for card in cards[: self.max_results]:
            link = card.find("a", href=True)
            title_el = card.find(["h2", "h3", "h4"])
            if not (link and title_el):
                continue
            href = link["href"]
            if not href.startswith("http"):
                href = BASE_URL + href

            job = Job(
                title=title_el.get_text(strip=True),
                company=card.get_text(" ", strip=True)[:80],
                location=location,
                url=href,
                platform=self.name,
            )
            jobs.append(job)

        return jobs

    def search(self, keywords: list[str], location: str) -> list[Job]:
        all_jobs: list[Job] = []
        seen_urls: set[str] = set()

        api_url = self._discover_api_url()

        for keyword in keywords[:6]:
            if len(all_jobs) >= self.max_results:
                break

            if api_url:
                jobs = self._search_via_api(keyword, location, api_url)
            else:
                jobs = self._search_via_html(keyword, location)

            for job in jobs:
                if job.url not in seen_urls:
                    seen_urls.add(job.url)
                    all_jobs.append(job)

        if not all_jobs:
            log.warning(
                "Engagement Jeunes: aucun résultat. "
                "Si le site fonctionne dans votre navigateur, ouvrez F12 → Réseau "
                "et cherchez l'appel XHR/Fetch lors d'une recherche d'offres. "
                "Copiez l'URL de base de l'API et mettez-la dans config.yaml "
                "sous plateformes.engagement_jeunes.api_url"
            )

        return all_jobs
