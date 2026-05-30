import logging
import re
import requests
from .base import BaseScraper, Job

log = logging.getLogger(__name__)

BASE        = "https://www.apec.fr"
HOME_URL    = f"{BASE}/candidat/recherche-emploi.html"
API_URL     = f"{BASE}/cms/webservices/rechercheOffre"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Content-Type":    "application/json",
    "Referer":         HOME_URL,
    "Origin":          BASE,
}

# Codes de département par ville (APEC filtre par département)
DEPT_CODES = {
    "paris":            [75, 92, 93, 94],   # Paris + petite couronne
    "île-de-france":    [75, 77, 78, 91, 92, 93, 94, 95],
    "nice":             [6],
    "marseille":        [13],
    "aix-en-provence":  [13],
    "sophia antipolis": [6],
    "lyon":             [69],
    "bordeaux":         [33],
    "toulouse":         [31],
    "lille":            [59],
    "remote":           [],
}

CONTRACT_CODES = {
    "CDI":        102506,
    "CDD":        102515,
    "Stage":      102499,
    "Alternance": 101807,
    "Freelance":  102505,
}


def _get_depts(location: str) -> list[int]:
    return DEPT_CODES.get(location.lower().split(",")[0].strip(), [])


def _parse_offer(item: dict) -> Job | None:
    title = item.get("intitule") or ""
    if not title:
        return None

    # Nom de l'entreprise — plusieurs champs possibles
    company = (
        item.get("nomCommercial")
        or item.get("nomEntreprise")
        or (item.get("entreprise") or {}).get("libelle")
        or "Entreprise non précisée"
    )

    # Numéro d'offre
    num = str(item.get("numeroOffre") or item.get("numOffre") or item.get("id") or "")
    if not num:
        return None
    url = f"{BASE}/candidat/recherche-emploi.html/emploi/{num}"

    # Localisation
    loc_raw  = item.get("lieuTravail") or item.get("lieuDeLocalisation") or {}
    if isinstance(loc_raw, dict):
        location = loc_raw.get("libelle") or loc_raw.get("ville") or "France"
    else:
        location = str(loc_raw) if loc_raw else "France"

    # Salaire
    sal_raw  = item.get("salaire") or {}
    salary   = (
        sal_raw.get("libelle") if isinstance(sal_raw, dict)
        else str(sal_raw) if sal_raw
        else item.get("salaireLibelle") or ""
    )

    contract = item.get("libelleTypeContrat") or item.get("typeContrat") or ""

    desc_raw = item.get("texteOffre") or item.get("texteBrief") or item.get("description") or ""
    desc     = re.sub(r"<[^>]+>", " ", str(desc_raw)).strip()[:500]

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
        self._session_ready = False

    def _init_session(self):
        """Visite la homepage pour récupérer les cookies de session APEC."""
        if self._session_ready:
            return
        try:
            self._session.get(HOME_URL, timeout=15)
            self._session_ready = True
        except Exception as e:
            log.debug(f"APEC: impossible d'initialiser la session: {e}")

    def search(self, keywords: list[str], location: str) -> list[Job]:
        jobs: list[Job] = []
        seen_urls: set[str] = set()

        self._init_session()

        contract_types = self.config.get("contrat", {}).get("types", [])
        contract_ids   = [CONTRACT_CODES[c] for c in contract_types if c in CONTRACT_CODES]
        depts          = _get_depts(location)

        for keyword in keywords[:6]:
            if len(jobs) >= self.max_results:
                break

            body = {
                "motsCles":  keyword,
                "lieux":     depts,
                "sorts":     [{"type": "DATE", "direction": "DESCENDING"}],
                "pagination": {
                    "startIndex": 0,
                    "range":      min(20, self.max_results),
                },
            }
            if contract_ids:
                body["typesContrat"] = contract_ids

            try:
                resp = self._session.post(API_URL, json=body, timeout=25)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                log.warning(f"APEC erreur pour '{keyword}' ({location}): {e}")
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
                "APEC: aucune offre. Ouvrez F12 → Réseau sur apec.fr, "
                "cherchez l'appel POST vers 'rechercheOffre' et vérifiez le body exact."
            )
        return jobs
