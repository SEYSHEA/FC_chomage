import logging
import time
import requests
from .base import BaseScraper, Job

log = logging.getLogger(__name__)

TOKEN_URL = (
    "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
    "?realm=%2Fpartenaire"
)
SEARCH_URL = (
    "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
)

# France Travail contract type codes
CONTRACT_MAP = {
    "CDI":        "CDI",
    "CDD":        "CDD",
    "Stage":      "STA",
    "Alternance": "ALT",
    "Intérim":    "MIS",
    "Freelance":  "LIB",
}


class FranceTravailScraper(BaseScraper):
    name = "France Travail"

    def __init__(self, config: dict):
        super().__init__(config)
        platform_cfg = config["plateformes"]["france_travail"]
        self.client_id = platform_cfg.get("client_id", "")
        self.client_secret = platform_cfg.get("client_secret", "")
        self._token: str = ""
        self._token_expiry: float = 0.0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry:
            return self._token

        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "api_offresdemploiv2 o2dsoffre",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 1400) - 60
        return self._token

    def search(self, keywords: list[str], location: str) -> list[Job]:
        jobs: list[Job] = []
        contract_types = self.config.get("contrat", {}).get("types", [])
        min_salary = self.config.get("salaire", {}).get("minimum", 0)
        radius = self.config.get("localisation", {}).get("rayon_km", 30)

        ft_types = [CONTRACT_MAP[c] for c in contract_types if c in CONTRACT_MAP]

        try:
            token = self._get_token()
        except Exception as e:
            log.error(f"France Travail: impossible d'obtenir le token: {e}")
            return jobs

        query_str = " OR ".join(f'"{kw}"' for kw in keywords[:5])

        params: dict = {
            "motsCles": query_str,
            "lieuTravail.libelle": location,
            "distance": radius,
            "sort": 1,      # Sort by date
            "range": f"0-{min(self.max_results - 1, 149)}",
        }
        if ft_types:
            params["typeContrat"] = ",".join(ft_types)
        if min_salary and min_salary > 0:
            params["salaire.montantMin"] = min_salary

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        try:
            resp = requests.get(SEARCH_URL, params=params, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            offers = data.get("resultats", [])
        except requests.HTTPError as e:
            log.error(f"France Travail API erreur {e.response.status_code}: {e}")
            return jobs
        except Exception as e:
            log.error(f"France Travail: {e}")
            return jobs

        for offer in offers:
            url = offer.get("origineOffre", {}).get("urlOrigine") or \
                  f"https://candidat.francetravail.fr/offres/recherche/detail/{offer.get('id', '')}"

            lieu = offer.get("lieuTravail", {})
            location_str = lieu.get("libelle", location)

            salary_info = offer.get("salaire", {})
            salary_str = salary_info.get("libelle", "")

            job = Job(
                title=offer.get("intitule", "Poste inconnu"),
                company=offer.get("entreprise", {}).get("nom", "Entreprise non précisée"),
                location=location_str,
                url=url,
                platform=self.name,
                contract_type=offer.get("typeContratLibelle", ""),
                salary=salary_str,
                description=offer.get("description", "")[:500],
                date_posted=offer.get("dateCreation", ""),
            )
            jobs.append(job)

        return jobs
