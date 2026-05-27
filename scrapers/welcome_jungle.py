import logging
import urllib.parse
import requests
from .base import BaseScraper, Job

log = logging.getLogger(__name__)

API_URL = "https://api.welcometothejungle.com/api/v1/jobs"

CONTRACT_MAP = {
    "CDI":        "full_time",
    "CDD":        "temporary",
    "Stage":      "internship",
    "Alternance": "apprenticeship",
    "Freelance":  "freelance",
}


class WelcomeJungleScraper(BaseScraper):
    name = "Welcome to the Jungle"

    def search(self, keywords: list[str], location: str) -> list[Job]:
        jobs: list[Job] = []
        contract_types = self.config.get("contrat", {}).get("types", [])
        include_remote = self.config.get("localisation", {}).get("inclure_remote", True)

        wtj_contracts = [CONTRACT_MAP[c] for c in contract_types if c in CONTRACT_MAP]

        # WTJ searches one keyword at a time; use the most specific ones
        search_terms = keywords[:8]

        seen_urls: set[str] = set()

        for keyword in search_terms:
            if len(jobs) >= self.max_results:
                break

            # Build params as list of tuples to support repeated keys
            param_list = [
                ("page", 1),
                ("per_page", min(20, self.max_results)),
                ("query", keyword),
                ("country_codes[]", "FR"),
            ]
            if include_remote:
                param_list.append(("remote[]", "fulltime"))
            for ct in wtj_contracts:
                param_list.append(("contract_type[]", ct))
            params = param_list

            headers = {
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "fr-FR,fr;q=0.9",
            }

            try:
                resp = requests.get(API_URL, params=param_list, headers=headers, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                log.warning(f"Welcome to the Jungle erreur pour '{keyword}': {e}")
                continue

            for item in data.get("jobs", []):
                url = f"https://www.welcometothejungle.com/fr/companies/{item.get('organization', {}).get('slug', '')}/jobs/{item.get('slug', '')}"

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                office = item.get("office", {})
                loc_city = office.get("city", location)
                loc_country = office.get("country", {}).get("name_fr", "France")
                loc_str = f"{loc_city}, {loc_country}" if loc_city else location

                contract = item.get("contract_type", {})
                contract_label = contract.get("name", {}).get("fr", "")

                salary_min = item.get("salary_minimum")
                salary_max = item.get("salary_maximum")
                salary_str = ""
                if salary_min or salary_max:
                    currency = item.get("salary_currency", "€")
                    if salary_min and salary_max:
                        salary_str = f"{salary_min:,} – {salary_max:,} {currency}/an"
                    elif salary_min:
                        salary_str = f"À partir de {salary_min:,} {currency}/an"

                job = Job(
                    title=item.get("name", "Poste inconnu"),
                    company=item.get("organization", {}).get("name", "Entreprise non précisée"),
                    location=loc_str,
                    url=url,
                    platform=self.name,
                    contract_type=contract_label,
                    salary=salary_str,
                    description=item.get("description", "")[:500],
                    date_posted=item.get("published_at", ""),
                )
                jobs.append(job)

        return jobs
