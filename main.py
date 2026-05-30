#!/usr/bin/env python3
"""
FC_Chômage – Recherche automatique d'offres d'emploi
=====================================================
Usage :
  python main.py            → Rechercher une fois et envoyer les notifications
  python main.py --test     → Tester sans envoyer de notifications Discord
  python main.py --loop     → Tourner en continu (intervalle défini dans config.yaml)
  python main.py --history  → Afficher les dernières offres trouvées
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import schedule
import yaml

from database.storage import Storage
from notifiers.discord import DiscordNotifier
from scrapers.apec import ApecScraper
from scrapers.engagement_jeunes import EngagementJeunesScraper
from scrapers.france_travail import FranceTravailScraper
from scrapers.hellowork import HelloWorkScraper
from scrapers.indeed import IndeedScraper
from scrapers.linkedin import LinkedInScraper
from scrapers.welcome_jungle import WelcomeJungleScraper
from utils.helpers import calculate_relevance, filter_jobs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─── Configuration ───────────────────────────────────────────────────────────

def load_config() -> dict:
    config_path = Path("config.yaml")
    if not config_path.exists():
        log.error("❌  config.yaml introuvable. Lancez ce script depuis le dossier FC_chomage.")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Merge .env secrets into config (overrides config.yaml if set)
    env_path = Path(".env")
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip()
                    if key == "FRANCE_TRAVAIL_CLIENT_ID" and val:
                        cfg["plateformes"]["france_travail"]["client_id"] = val
                    elif key == "FRANCE_TRAVAIL_CLIENT_SECRET" and val:
                        cfg["plateformes"]["france_travail"]["client_secret"] = val
                    elif key == "LINKEDIN_LI_AT_COOKIE" and val:
                        cfg["plateformes"]["linkedin"]["li_at_cookie"] = val
                    elif key == "DISCORD_WEBHOOK_URL" and val:
                        cfg["notifications"]["discord"]["webhook_url"] = val

    return cfg


# ─── Search runner ───────────────────────────────────────────────────────────

def run_search(config: dict, storage: Storage, notifier: DiscordNotifier, dry_run: bool = False) -> int:
    log.info("🔍  Démarrage de la recherche d'offres…")

    keywords        = config["mots_cles"]["principaux"]
    exclude_kw      = config["mots_cles"].get("exclusions", [])
    location        = config["localisation"]["ville"]
    include_remote  = config["localisation"].get("inclure_remote", True)
    contract_types  = config["contrat"]["types"]
    min_salary      = config["salaire"].get("minimum", 0)
    show_no_salary  = config["salaire"].get("afficher_sans_salaire", True)

    # Build scraper list based on config
    scrapers = []
    ft_cfg = config["plateformes"].get("france_travail", {})
    if ft_cfg.get("active") and ft_cfg.get("client_id"):
        scrapers.append(FranceTravailScraper(config))
    elif ft_cfg.get("active"):
        log.warning("⚠️   France Travail ignoré (client_id manquant dans .env ou config.yaml)")

    if config["plateformes"].get("indeed", {}).get("active"):
        scrapers.append(IndeedScraper(config))

    if config["plateformes"].get("welcome_jungle", {}).get("active"):
        scrapers.append(WelcomeJungleScraper(config))

    if config["plateformes"].get("linkedin", {}).get("active"):
        scrapers.append(LinkedInScraper(config))

    if config["plateformes"].get("engagement_jeunes", {}).get("active"):
        scrapers.append(EngagementJeunesScraper(config))

    if config["plateformes"].get("apec", {}).get("active"):
        scrapers.append(ApecScraper(config))

    if config["plateformes"].get("hellowork", {}).get("active"):
        scrapers.append(HelloWorkScraper(config))

    if not scrapers:
        log.error("❌  Aucune plateforme active. Vérifiez config.yaml.")
        return 0

    new_jobs_total = 0

    for scraper in scrapers:
        log.info(f"   ↳  {scraper.name}…")
        try:
            raw_jobs = scraper.search(keywords, location)
        except Exception as e:
            log.error(f"   ❌  {scraper.name}: {e}")
            continue

        filtered = filter_jobs(
            raw_jobs, keywords, exclude_kw, contract_types,
            min_salary, show_no_salary, include_remote, location,
        )

        for job in filtered:
            job.relevance_score = calculate_relevance(job, keywords, exclude_kw)

        # Sort best matches first
        filtered.sort(key=lambda j: j.relevance_score, reverse=True)

        new_from_scraper = 0
        for job in filtered:
            if storage.job_exists(job.id):
                continue

            storage.save_job(job)
            new_from_scraper += 1
            new_jobs_total += 1

            stars = "⭐" * min(int(job.relevance_score), 5) or "—"
            log.info(f"      ✅  {job.title}  |  {job.company}  |  {stars}")

            if not dry_run and notifier.is_active():
                notifier.notify(job)
                storage.mark_notified(job.id)
                time.sleep(0.5)   # Respect Discord rate limit

        log.info(f"   ↳  {scraper.name}: {len(filtered)} filtrées, {new_from_scraper} nouvelles")

    log.info(f"✅  Recherche terminée — {new_jobs_total} nouvelle(s) offre(s)")

    if not dry_run and notifier.is_active():
        notifier.send_summary(new_jobs_total, storage.count_jobs())

    return new_jobs_total


# ─── History ─────────────────────────────────────────────────────────────────

def show_history(storage: Storage):
    jobs = storage.get_recent_jobs(limit=20)
    if not jobs:
        print("\nAucune offre dans l'historique. Lancez d'abord une recherche.\n")
        return

    print(f"\n📋  Dernières {len(jobs)} offres trouvées :\n")
    for job in jobs:
        score_stars = "⭐" * min(int(job.get("relevance_score", 0)), 5) or "—"
        print(f"  [{job['platform']}] {job['title']}  —  {job['company']}")
        print(f"  📍 {job['location']}  |  💼 {job['contract_type'] or '?'}  |  {score_stars}")
        print(f"  🔗 {job['url']}")
        print(f"  📅 Trouvé le {job['date_found'][:16]}\n")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="FC_Chômage – Recherche automatique d'offres d'emploi",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples :\n"
            "  python main.py           → une recherche + notifications\n"
            "  python main.py --test    → une recherche sans notifications\n"
            "  python main.py --loop    → recherche continue\n"
            "  python main.py --history → voir les offres déjà trouvées\n"
        ),
    )
    parser.add_argument("--test",    action="store_true", help="Tester sans envoyer de notifications")
    parser.add_argument("--loop",    action="store_true", help="Tourner en continu selon l'intervalle configuré")
    parser.add_argument("--history", action="store_true", help="Afficher l'historique des offres")
    args = parser.parse_args()

    config   = load_config()
    storage  = Storage()
    notifier = DiscordNotifier(config)

    if args.history:
        show_history(storage)
        return

    if args.test:
        log.info("🧪  MODE TEST — aucune notification ne sera envoyée")
        run_search(config, storage, notifier, dry_run=True)
        return

    if args.loop:
        interval = config.get("recherche", {}).get("intervalle_minutes", 60)
        log.info(f"🔄  Mode continu — recherche toutes les {interval} minutes")
        run_search(config, storage, notifier)
        schedule.every(interval).minutes.do(run_search, config, storage, notifier)
        while True:
            schedule.run_pending()
            time.sleep(30)
    else:
        run_search(config, storage, notifier)


if __name__ == "__main__":
    main()
