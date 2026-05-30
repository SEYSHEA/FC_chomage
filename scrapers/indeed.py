import logging
from .base import BaseScraper, Job

log = logging.getLogger(__name__)

try:
    from jobspy import scrape_jobs
    JOBSPY_OK = True
except ImportError:
    JOBSPY_OK = False


class IndeedScraper(BaseScraper):
    name = "Indeed"

    def search(self, keywords: list[str], location: str) -> list[Job]:
        if not JOBSPY_OK:
            log.warning(
                "Indeed désactivé — installez la dépendance : pip install python-jobspy"
            )
            return []

        jobs: list[Job] = []
        seen_urls: set[str] = set()

        # Regroupe les mots-clés par lots de 3 pour limiter les requêtes
        batches = [keywords[i:i+3] for i in range(0, min(len(keywords), 9), 3)]

        for batch in batches:
            if len(jobs) >= self.max_results:
                break

            query = " OR ".join(f'"{kw}"' for kw in batch)

            try:
                df = scrape_jobs(
                    site_name=["indeed"],
                    search_term=query,
                    location=location,
                    results_wanted=min(self.max_results, 20),
                    hours_old=self.days_back * 24,
                    country_indeed="France",
                    verbose=0,
                )
            except Exception as e:
                log.warning(f"Indeed erreur pour '{query}' ({location}): {e}")
                continue

            if df is None or df.empty:
                continue

            for _, row in df.iterrows():
                url = str(row.get("job_url") or "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                salary_parts = []
                s_min = row.get("min_amount")
                s_max = row.get("max_amount")
                s_cur = row.get("currency") or "€"
                s_int = row.get("interval") or ""
                if s_min and s_max:
                    salary_parts = [f"{int(s_min):,} – {int(s_max):,} {s_cur}"]
                elif s_min:
                    salary_parts = [f"À partir de {int(s_min):,} {s_cur}"]
                if s_int and salary_parts:
                    salary_parts.append(f"/{s_int}")
                salary = "".join(salary_parts)

                date = str(row.get("date_posted") or "")[:10]
                desc = str(row.get("description") or "")[:500]

                job = Job(
                    title=str(row.get("title") or "Poste inconnu"),
                    company=str(row.get("company") or "Entreprise non précisée"),
                    location=str(row.get("location") or location),
                    url=url,
                    platform=self.name,
                    contract_type=str(row.get("job_type") or ""),
                    salary=salary,
                    description=desc,
                    date_posted=date,
                )
                jobs.append(job)

        return jobs
