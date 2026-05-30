import logging
import re
import requests
from .base import BaseScraper, Job

log = logging.getLogger(__name__)

BASE = "https://www.apec.fr"
API_URL = f"{BASE}/cms/webservices/rechercheOffre/public"

# APEC contract type IDs
CONTRACT_IDS = {
    "CDI":        102506,
    "CDD":        102515,
    "Stage":      102499,
    "Alternance": 101807,
    "Freelance":  102505,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Referer": f"{BASE}/candidat/recherche-emploi.html",
    "Origin": BASE,
    "X-Requested-With": "XMLHttpRequest",
}


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[àáâãäå]", "a", text)
    text = re.sub(r"[èéêë]", "e", text)
    text = re.sub(r"[ìíîï]", "i", text)
    text = re.sub(r"[òóôõö]", "o", text)
    text = re.sub(r"[ùúûü]", "u", text)
    text = re.sub(r"[ç]", "c", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _parse_offer(item: dict) -> Job | None:
    title = item.get("intitulePoste") or item.get("title") or ""
    if not title:
        return None

    company = item.get("nomSociete") or item.get("company") or "Entreprise non précisée"
    location = item.get("lieuTravail") or item.get("lieu") or "France"
    salary = item.get("salaireLibelle") or item.get("salaire") or ""
    contract = item.get("typeContrat") or item.get("libelleSecteur") or ""

    # Build URL from offer number
    numero = str(item.get("numeroDOffre") or item.get("id") or "")
    if numero:
        slug = _slugify(title)
        url = f"{BASE}/candidat/recherche-emploi.html/emploi/{numero}/{slug}"
    else:
        url = item.get("url") or item.get("urlOffre") or ""
    if not url:
        return None

    # Date : APEC returns epoch ms
    date_raw = item.get("dateCreation") or item.get("datePublication") or ""
    date_str = ""
    if isinstance(date_raw, (int, float)) and date_raw > 0:
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(date_raw / 1000, tz=timezone.utc)
        date_str = dt.strftime("%Y-%m-%d")
    elif isinstance(date_raw, str):
        date_str = date_raw[:10]

    desc = (
        item.get("texteHtml") or item.get("description") or item.get("resume") or ""
    )
    # Strip basic HTML tags
    desc = re.sub(r"<[^>]+>", " ", str(desc)).strip()[:500]

    return Job(
        title=str(title),
        company=str(company),
        location=str(location),
        url=url,
        platform="APEC",
        contract_type=str(contract),
        salary=str(salary),
        description=desc,
        date_posted=date_str,
    )


class ApecScraper(BaseScraper):
    name = "APEC"

    def __init__(self, config: dict):
        super().__init__(config)
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def search(self, keywords: list[str], location: str) -> list[Job]:
        jobs: list[Job] = []
        seen_urls: set[str] = set()

        contract_types = self.config.get("contrat", {}).get("types", [])
        contract_ids = [CONTRACT_IDS[c] for c in contract_types if c in CONTRACT_IDS]

        for keyword in keywords[:6]:
            if len(jobs) >= self.max_results:
                break

            # Build params as list of tuples (repeated keys for arrays)
            params: list[tuple] = [
                ("motsCles", keyword),
                ("nbParPage", min(20, self.max_results)),
                ("page", 0),
            ]
            if contract_ids:
                for cid in contract_ids:
                    params.append(("typesContrat[]", cid))

            try:
                resp = self._session.get(API_URL, params=params, timeout=25)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                log.warning(f"APEC erreur pour '{keyword}': {e}")
                continue

            results = (
                data.get("results")
                or data.get("offres")
                or data.get("data")
                or (data if isinstance(data, list) else [])
            )

            for item in results[: self.max_results]:
                job = _parse_offer(item)
                if job and job.url not in seen_urls:
                    seen_urls.add(job.url)
                    jobs.append(job)

        if not jobs:
            log.warning(
                "APEC: aucune offre trouvée. "
                "Si le site fonctionne dans votre navigateur, "
                "vérifiez que les clés API APEC n'ont pas changé "
                "(F12 → Réseau → filtrer 'rechercheOffre')."
            )
        return jobs
