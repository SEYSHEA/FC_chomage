import logging
import re
import time
import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, Job

log = logging.getLogger(__name__)

SEARCH_URL = "https://fr.indeed.com/emplois"

HEADERS = {
    # macOS + Chrome User-Agent — moins filtré qu'un Windows UA sur Indeed FR
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}


def _parse_cards(soup: BeautifulSoup, location: str) -> list[Job]:
    jobs: list[Job] = []

    # Indeed refreshes selectors often — try in order of reliability
    cards = (
        soup.select("div.job_seen_beacon")
        or soup.select("li.css-1ac2h1w")
        or soup.select("[data-jk]")
        or soup.select("div[class*='jobCard']")
    )

    for card in cards:
        # Title + URL
        title_el = (
            card.select_one("h2.jobTitle a span")
            or card.select_one("h2 a span")
            or card.select_one("a[data-jk] span")
            or card.select_one("h2 span")
        )
        link_el = (
            card.select_one("h2.jobTitle a[href]")
            or card.select_one("a[data-jk]")
            or card.select_one("a[href*='/rc/clk']")
            or card.select_one("a[href*='/pagead/clk']")
        )

        if not title_el or not link_el:
            continue

        title = title_el.get_text(strip=True)
        href  = link_el.get("href", "")
        if not href.startswith("http"):
            href = "https://fr.indeed.com" + href

        # Company
        company_el = (
            card.select_one("[data-testid='company-name']")
            or card.select_one("span.companyName")
            or card.select_one("a.companyName")
            or card.select_one("[class*='companyName']")
        )
        company = company_el.get_text(strip=True) if company_el else "Entreprise non précisée"

        # Location
        loc_el = (
            card.select_one("[data-testid='text-location']")
            or card.select_one("div.companyLocation")
            or card.select_one("[class*='companyLocation']")
        )
        loc = loc_el.get_text(strip=True) if loc_el else location

        # Salary (optional)
        sal_el = (
            card.select_one("[data-testid='attribute_snippet_testid']")
            or card.select_one("div.salary-snippet-container")
            or card.select_one("[class*='salary']")
        )
        salary = sal_el.get_text(strip=True) if sal_el else ""

        jobs.append(Job(
            title=title,
            company=company,
            location=loc,
            url=href,
            platform="Indeed",
            salary=salary,
        ))

    return jobs


class IndeedScraper(BaseScraper):
    name = "Indeed"

    def __init__(self, config: dict):
        super().__init__(config)
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def search(self, keywords: list[str], location: str) -> list[Job]:
        jobs: list[Job] = []
        seen_urls: set[str] = set()
        rayon = self.config.get("localisation", {}).get("rayon_km", 50)

        # One keyword per request — avoids complex OR queries that trigger blocks
        for i, keyword in enumerate(keywords[:6]):
            if len(jobs) >= self.max_results:
                break

            if i > 0:
                time.sleep(4)  # respecter le rate-limit Indeed

            params = {
                "q":       keyword,
                "l":       location,
                "sort":    "date",
                "fromage": str(self.days_back),
                "radius":  str(rayon),
            }

            try:
                resp = self._session.get(SEARCH_URL, params=params, timeout=25)
                resp.raise_for_status()
            except Exception as e:
                log.warning(f"Indeed erreur pour '{keyword}' ({location}): {e}")
                continue

            soup  = BeautifulSoup(resp.text, "html.parser")
            cards = _parse_cards(soup, location)

            if not cards:
                log.debug(
                    f"Indeed: aucune carte trouvée pour '{keyword}' ({location}). "
                    "Les sélecteurs HTML ont peut-être changé."
                )

            for job in cards[: self.max_results]:
                if job.url not in seen_urls:
                    seen_urls.add(job.url)
                    jobs.append(job)

        return jobs
