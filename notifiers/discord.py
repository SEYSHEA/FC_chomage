import logging
import time
import requests
from datetime import datetime
from scrapers.base import Job

log = logging.getLogger(__name__)

# Color codes for Discord embeds
COLOR_HIGH = 0x2ECC71    # Green  – highly relevant
COLOR_MED  = 0x3498DB    # Blue   – relevant
COLOR_LOW  = 0x95A5A6    # Grey   – low relevance

PLATFORM_EMOJIS = {
    "France Travail":        "🇫🇷",
    "Indeed":                "🔍",
    "Welcome to the Jungle": "🌴",
    "LinkedIn":              "💼",
    "APEC":                  "🎯",
    "HelloWork":             "👋",
}


def _score_to_color(score: float) -> int:
    if score >= 5:
        return COLOR_HIGH
    if score >= 2:
        return COLOR_MED
    return COLOR_LOW


class DiscordNotifier:
    def __init__(self, config: dict):
        notif_cfg = config.get("notifications", {}).get("discord", {})
        self.active = notif_cfg.get("active", False)
        self.webhook_url = notif_cfg.get("webhook_url", "").strip()

    def is_active(self) -> bool:
        return self.active and bool(self.webhook_url)

    def notify(self, job: Job) -> bool:
        if not self.is_active():
            return False

        emoji = PLATFORM_EMOJIS.get(job.platform, "📋")
        color = _score_to_color(job.relevance_score)

        fields = [
            {"name": "🏢 Entreprise", "value": job.company or "Non précisée", "inline": True},
            {"name": "📍 Lieu",       "value": job.location or "Non précisé", "inline": True},
        ]
        if job.contract_type:
            fields.append({"name": "📋 Contrat", "value": job.contract_type, "inline": True})
        if job.salary:
            fields.append({"name": "💰 Salaire", "value": job.salary, "inline": True})
        if job.date_posted:
            fields.append({"name": "📅 Publiée le", "value": job.date_posted[:10], "inline": True})

        payload = {
            "embeds": [{
                "title": f"🆕 {job.title}",
                "url": job.url,
                "color": color,
                "fields": fields,
                "footer": {
                    "text": (
                        f"{emoji} {job.platform}  •  "
                        f"Pertinence: {'⭐' * min(int(job.relevance_score), 5)}  •  "
                        f"{datetime.now().strftime('%d/%m/%Y %H:%M')}"
                    )
                },
            }]
        }

        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            if resp.status_code == 429:
                # Discord rate limit – wait and retry once
                retry_after = resp.json().get("retry_after", 2)
                log.warning(f"Discord rate limit, attente {retry_after}s…")
                time.sleep(retry_after)
                resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except Exception as e:
            log.error(f"Erreur envoi Discord: {e}")
            return False

    def send_summary(self, new_count: int, total_count: int):
        """Send a brief summary message when no new jobs are found."""
        if not self.is_active():
            return
        payload = {
            "content": (
                f"🔄 Recherche terminée — **{new_count} nouvelle(s) offre(s)** trouvée(s) "
                f"(total en base : {total_count})\n"
                f"*{datetime.now().strftime('%d/%m/%Y à %H:%M')}*"
            )
        }
        try:
            requests.post(self.webhook_url, json=payload, timeout=10)
        except Exception:
            pass
