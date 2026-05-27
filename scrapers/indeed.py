import logging
import urllib.parse
import xml.etree.ElementTree as ET
import requests
from .base import BaseScraper, Job

log = logging.getLogger(__name__)

RSS_URL = "https://fr.indeed.com/rss"


class IndeedScraper(BaseScraper):
    name = "Indeed"

    def search(self, keywords: list[str], location: str) -> list[Job]:
        jobs: list[Job] = []

        # Top 5 keywords joined with OR for best results
        query = " OR ".join(f'"{kw}"' for kw in keywords[:5])

        params = {
            "q": query,
            "l": location,
            "sort": "date",
            "fromage": str(self.days_back),
            "radius": str(self.config.get("localisation", {}).get("rayon_km", 50)),
            "limit": str(min(self.max_results, 50)),
        }
        url = f"{RSS_URL}?{urllib.parse.urlencode(params)}"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

        try:
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
        except ET.ParseError as e:
            log.error(f"Indeed: erreur de parsing RSS: {e}")
            return jobs
        except Exception as e:
            log.error(f"Indeed RSS erreur: {e}")
            return jobs

        ns = {"content": "http://purl.org/rss/1.0/modules/content/"}

        for item in root.findall(".//item")[: self.max_results]:
            title_el   = item.find("title")
            link_el    = item.find("link")
            desc_el    = item.find("description")
            pubdate_el = item.find("pubDate")

            title_raw = title_el.text or "" if title_el is not None else ""
            link      = link_el.text or ""   if link_el is not None else ""
            desc      = desc_el.text or ""   if desc_el is not None else ""
            pub_date  = pubdate_el.text or "" if pubdate_el is not None else ""

            # Indeed RSS title format: "Job Title - Company - Location"
            parts = title_raw.split(" - ")
            clean_title = parts[0].strip() if parts else title_raw
            company     = parts[1].strip() if len(parts) > 1 else "Entreprise non précisée"
            loc         = parts[2].strip() if len(parts) > 2 else location

            if not link:
                continue

            job = Job(
                title=clean_title,
                company=company,
                location=loc,
                url=link,
                platform=self.name,
                description=desc[:500],
                date_posted=pub_date,
            )
            jobs.append(job)

        return jobs
