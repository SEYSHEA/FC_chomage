import logging
import re
import time
import urllib.parse
import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, Job

log = logging.getLogger(__name__)

# LinkedIn guest job search — no auth required but limited results
GUEST_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

# Base headers that mimic a real browser
BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.linkedin.com/jobs/search/",
}

# f_TPR values: r86400 = 24h, r604800 = 7j, r2592000 = 30j
TIMEFRAME = {1: "r86400", 3: "r259200", 7: "r604800", 30: "r2592000"}


def _days_to_tpr(days: int) -> str:
    for threshold, code in sorted(TIMEFRAME.items()):
        if days <= threshold:
            return code
    return "r604800"


class LinkedInScraper(BaseScraper):
    name = "LinkedIn"

    def __init__(self, config: dict):
        super().__init__(config)
        li_cfg = config.get("plateformes", {}).get("linkedin", {})
        self.li_at_cookie: str = li_cfg.get("li_at_cookie", "").strip()

    def _build_headers(self) -> dict:
        headers = dict(BASE_HEADERS)
        if self.li_at_cookie:
            headers["Cookie"] = f"li_at={self.li_at_cookie}; lang=v=2&lang=fr-fr"
        return headers

    def search(self, keywords: list[str], location: str) -> list[Job]:
        jobs: list[Job] = []
        seen_ids: set[str] = set()
        headers = self._build_headers()
        tpr = _days_to_tpr(self.days_back)

        for keyword in keywords[:6]:
            if len(jobs) >= self.max_results:
                break

            params = {
                "keywords": keyword,
                "location": location,
                "f_TPR": tpr,
                "start": 0,
                "count": 25,
            }

            try:
                resp = requests.get(
                    GUEST_URL, params=params, headers=headers, timeout=20
                )
                resp.raise_for_status()
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else "?"
                if code == 429:
                    log.warning("LinkedIn: limite de requêtes atteinte, pause 10s…")
                    time.sleep(10)
                else:
                    log.warning(f"LinkedIn: erreur HTTP {code} pour '{keyword}'")
                continue
            except Exception as e:
                log.warning(f"LinkedIn: erreur réseau pour '{keyword}': {e}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.find_all("div", class_=re.compile(r"base-search-card"))

            if not cards:
                log.debug(f"LinkedIn: aucune carte trouvée pour '{keyword}'")
                continue

            for card in cards:
                # Extract job ID from the apply link to deduplicate
                link_el = card.find("a", class_=re.compile(r"base-card__full-link"))
                if not link_el:
                    link_el = card.find("a", href=re.compile(r"/jobs/view/"))
                if not link_el:
                    continue

                raw_url = link_el.get("href", "")
                # Keep only the canonical job URL (strip tracking params)
                match = re.search(r"(https://www\.linkedin\.com/jobs/view/\d+)", raw_url)
                url = match.group(1) if match else raw_url.split("?")[0]

                job_id = re.search(r"/jobs/view/(\d+)", url)
                uid = job_id.group(1) if job_id else url
                if uid in seen_ids:
                    continue
                seen_ids.add(uid)

                title_el   = card.find(class_=re.compile(r"base-search-card__title"))
                company_el = card.find(class_=re.compile(r"base-search-card__subtitle"))
                loc_el     = card.find(class_=re.compile(r"job-search-card__location"))
                time_el    = card.find("time")
                badge_el   = card.find(class_=re.compile(r"job-search-card__benefits"))

                title    = title_el.get_text(strip=True)   if title_el   else "Poste inconnu"
                company  = company_el.get_text(strip=True) if company_el else "Entreprise non précisée"
                location_ = loc_el.get_text(strip=True)    if loc_el     else location
                date     = time_el.get("datetime", "")     if time_el    else ""
                contract = badge_el.get_text(strip=True)   if badge_el   else ""

                if not url:
                    continue

                job = Job(
                    id=f"linkedin_{uid}",
                    title=title,
                    company=company,
                    location=location_,
                    url=url,
                    platform=self.name,
                    contract_type=contract,
                    date_posted=date,
                )
                jobs.append(job)

            time.sleep(1.5)  # Be respectful to LinkedIn's servers

        return jobs
