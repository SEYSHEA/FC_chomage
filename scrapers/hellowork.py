import json
import logging
import re
import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, Job

log = logging.getLogger(__name__)

BASE = "https://www.hellowork.com"
SEARCH_URL = f"{BASE}/fr-fr/emploi/recherche.html"

CONTRACT_MAP = {
    "CDI":        "cdi",
    "CDD":        "cdd",
    "Stage":      "stage",
    "Alternance": "alternance",
    "Freelance":  "freelance",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Referer": f"{BASE}/fr-fr/emploi/recherche.html",
}


def _extract_next_data(html: str) -> list[dict]:
    """Extract job list from __NEXT_DATA__ embedded JSON."""
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return []

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

    props = data.get("props", {}).get("pageProps", {})

    # Try several known HelloWork page structure paths
    for path in [
        ["jobs"],
        ["searchResults", "jobs"],
        ["initialState", "jobs", "list"],
        ["data", "jobs"],
        ["jobOffers"],
        ["offers"],
    ]:
        node = props
        for key in path:
            if isinstance(node, dict):
                node = node.get(key)
        if isinstance(node, list) and node:
            return node

    # Scan dehydratedState queries
    for query in props.get("dehydratedState", {}).get("queries", []):
        inner = query.get("state", {}).get("data", {})
        for key in ("jobs", "results", "offers", "jobOffers", "data"):
            val = inner.get(key) if isinstance(inner, dict) else None
            if isinstance(val, list) and val:
                return val

    return []


def _extract_html_cards(html: str, location: str) -> list[Job]:
    """Fallback: parse job cards from HTML with BeautifulSoup."""
    jobs: list[Job] = []
    soup = BeautifulSoup(html, "html.parser")

    # Common selectors for HelloWork job cards
    for selector in ["article[data-id]", "li[data-id]", "article.job", "li.job", "article"]:
        cards = soup.select(selector)
        if len(cards) > 2:
            break

    for card in cards[:30]:
        link = card.find("a", href=True)
        title_el = card.find(["h2", "h3", "h4"])
        if not (link and title_el):
            continue

        href = link["href"]
        if not href.startswith("http"):
            href = BASE + href

        # Try to find company name
        company_el = card.find(class_=re.compile(r"company|entreprise|nom", re.I))
        company = company_el.get_text(strip=True) if company_el else "Entreprise non précisée"

        job = Job(
            title=title_el.get_text(strip=True),
            company=company,
            location=location,
            url=href,
            platform="HelloWork",
        )
        jobs.append(job)

    return jobs


def _parse_json_offer(item: dict, location: str) -> Job | None:
    title = (
        item.get("title")
        or item.get("name")
        or item.get("label")
        or item.get("jobTitle")
        or ""
    )
    if not title:
        return None

    company = (
        item.get("company") or item.get("companyName")
        or (item.get("employer") or {}).get("name")
        or "Entreprise non précisée"
    )

    loc = (
        item.get("location") or item.get("city")
        or item.get("place") or location
    )

    url = item.get("url") or item.get("applyUrl") or item.get("link") or ""
    if url and not url.startswith("http"):
        url = BASE + url

    slug = item.get("slug") or item.get("id") or ""
    if not url and slug:
        url = f"{BASE}/fr-fr/emploi/{slug}.html"
    if not url:
        return None

    contract = (
        item.get("contractType") or item.get("contract_type")
        or item.get("type") or ""
    )
    if isinstance(contract, dict):
        contract = contract.get("label") or contract.get("name") or ""

    salary = item.get("salary") or item.get("salaire") or ""
    if isinstance(salary, dict):
        min_s = salary.get("min") or salary.get("minimum")
        max_s = salary.get("max") or salary.get("maximum")
        currency = salary.get("currency", "€")
        if min_s and max_s:
            salary = f"{min_s:,} – {max_s:,} {currency}/an"
        elif min_s:
            salary = f"À partir de {min_s:,} {currency}/an"
        else:
            salary = ""

    desc = item.get("description") or item.get("summary") or ""
    date = item.get("publishedAt") or item.get("date") or item.get("created_at") or ""

    return Job(
        title=str(title),
        company=str(company),
        location=str(loc),
        url=str(url),
        platform="HelloWork",
        contract_type=str(contract),
        salary=str(salary),
        description=str(desc)[:500],
        date_posted=str(date)[:10],
    )


class HelloWorkScraper(BaseScraper):
    name = "HelloWork"

    def __init__(self, config: dict):
        super().__init__(config)
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def search(self, keywords: list[str], location: str) -> list[Job]:
        jobs: list[Job] = []
        seen_urls: set[str] = set()

        contract_types = self.config.get("contrat", {}).get("types", [])
        hw_contracts = [CONTRACT_MAP[c] for c in contract_types if c in CONTRACT_MAP]

        for keyword in keywords[:6]:
            if len(jobs) >= self.max_results:
                break

            params: list[tuple] = [
                ("k", keyword),
                ("l", location),
                ("d", 50),   # rayon 50 km
                ("p", 1),
            ]
            for ct in hw_contracts:
                params.append(("c[]", ct))

            try:
                resp = self._session.get(SEARCH_URL, params=params, timeout=25)
                resp.raise_for_status()
                html = resp.text
            except Exception as e:
                log.warning(f"HelloWork erreur pour '{keyword}': {e}")
                continue

            # Attempt 1 : __NEXT_DATA__
            raw_jobs = _extract_next_data(html)
            if raw_jobs:
                for item in raw_jobs[: self.max_results]:
                    job = _parse_json_offer(item, location)
                    if job and job.url not in seen_urls:
                        seen_urls.add(job.url)
                        jobs.append(job)
            else:
                # Attempt 2 : HTML parsing
                html_jobs = _extract_html_cards(html, location)
                for job in html_jobs:
                    if job.url not in seen_urls:
                        seen_urls.add(job.url)
                        jobs.append(job)

                if not html_jobs:
                    log.debug(
                        f"HelloWork: aucune offre extraite pour '{keyword}'. "
                        "Le site a peut-être changé de structure."
                    )

        return jobs
