import logging
import re
import requests
from .base import BaseScraper, Job

log = logging.getLogger(__name__)

BASE    = "https://www.apec.fr"
API_URL = f"{BASE}/cms/webservices/rechercheOffre/rechercheOffre"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Content-Type":    "application/json",
    "Referer":         f"{BASE}/candidat/recherche-emploi.html",
    "Origin":          BASE,
}

# Codes APEC pour les types de contrat (POST body)
CONTRACT_CODES = {
    "CDI":        102506,
    "CDD":        102515,
    "Stage":      102499,
    "Alternance": 101807,
    "Freelance":  102505,
}


def _parse_offer(item: dict) -> Job | None:
    title = item.get("intitule") or item.get("intitulePoste") or ""
    if not title:
        return None

    company  = item.get("nomEntreprise") or item.get("nomSociete") or "Entreprise non précisée"
    salary   = item.get("salaireLibelle") or item.get("salaire") or ""
    contract = item.get("libelleTypeContrat") or item.get("typeContrat") or ""
    desc_raw = item.get("texteBrief") or item.get("texteHtml") or item.get("description") or ""
    desc     = re.sub(r"<[^>]+>", " ", str(desc_raw)).strip()[:500]

    # Localisation — peut être une string ou un dict
    loc_raw  = item.get("lieuDeLocalisation") or item.get("lieuTravail") or {}
    if isinstance(loc_raw, dict):
        location = loc_raw.get("libelle") or loc_raw.get("ville") or "France"
    else:
        location = str(loc_raw) if loc_raw else "France"

    # Numéro d'offre pour construire l'URL
    num = str(item.get("numOffre") or item.get("numeroDOffre") or item.get("id") or "")
    if not num:
        return None
    url = f"{BASE}/candidat/recherche-emploi.html/emploi/{num}"

    # Date — APEC renvoie parfois un timestamp ms
    date_raw = item.get("datePublication") or item.get("dateCreation") or ""
    date_str = ""
    if isinstance(date_raw, (int, float)) and date_raw > 0:
        from datetime import datetime, timezone
        date_str = datetime.fromtimestamp(date_raw / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    elif isinstance(date_raw, str):
        date_str = date_raw[:10]

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
        contract_ids   = [CONTRACT_CODES[c] for c in contract_types if c in CONTRACT_CODES]

        for keyword in keywords[:6]:
            if len(jobs) >= self.max_results:
                break

            body = {
                "motsCles":           keyword,
                "typeContrat":        contract_ids,   # [] = tous les types
                "lieu":               [],              # [] = toute la France
                "nbResultatsParPage": min(20, self.max_results),
                "numeroPage":         0,
                "tri":                1,               # tri par date
            }

            try:
                resp = self._session.post(API_URL, json=body, timeout=25)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                log.warning(f"APEC erreur pour '{keyword}': {e}")
                continue

            if not isinstance(data, dict):
                log.warning(f"APEC: réponse inattendue ({type(data).__name__})")
                continue

            resultats = data.get("resultats") or data.get("results") or []
            for item in resultats[: self.max_results]:
                job = _parse_offer(item)
                if job and job.url not in seen_urls:
                    seen_urls.add(job.url)
                    jobs.append(job)

        if not jobs:
            log.warning(
                "APEC: aucune offre. Si le site fonctionne dans votre navigateur, "
                "ouvrez F12 → Réseau et cherchez l'appel POST vers 'rechercheOffre'."
            )
        return jobs
