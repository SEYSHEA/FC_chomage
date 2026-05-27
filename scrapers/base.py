import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    platform: str
    id: str = ""
    contract_type: str = ""
    salary: str = ""
    description: str = ""
    date_posted: str = ""
    relevance_score: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = hashlib.md5(self.url.encode("utf-8")).hexdigest()


class BaseScraper(ABC):
    name: str = "Base"

    def __init__(self, config: dict):
        self.config = config
        self.max_results = config.get("recherche", {}).get("max_offres_par_recherche", 30)
        self.days_back = config.get("recherche", {}).get("jours_en_arriere", 7)

    @abstractmethod
    def search(self, keywords: list[str], location: str) -> list[Job]:
        pass
