# FC_Chômage — Recherche automatique d'offres d'emploi

Système qui surveille automatiquement les offres d'emploi sur plusieurs plateformes et vous envoie des notifications Discord dès qu'une offre correspond à votre profil.

---

## Plateformes surveillées

| Plateforme         | Méthode         | Clé API requise |
|--------------------|-----------------|-----------------|
| France Travail     | API officielle  | Oui (gratuite)  |
| Indeed             | Flux RSS        | Non             |
| Welcome to the Jungle | API publique | Non             |

---

## Installation (5 minutes)

### 1. Prérequis

- Python 3.10 ou plus récent
- Pip (gestionnaire de paquets Python)

### 2. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 3. Configurer vos critères

Ouvrez `config.yaml` dans un éditeur de texte et modifiez :
- `mots_cles.principaux` — vos mots-clés de recherche
- `localisation.ville` — votre ville
- `contrat.types` — les types de contrats qui vous intéressent
- `salaire.minimum` — votre salaire minimum souhaité

### 4. Configurer Discord

1. Ouvrez votre serveur Discord
2. Cliquez sur l'engrenage ⚙️ à côté d'un canal
3. Allez dans **Intégrations** → **Webhooks**
4. Cliquez sur **Nouveau webhook**
5. Copiez l'URL du webhook

Créez un fichier `.env` (copiez `.env.example`) :

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...votre_url...
```

### 5. (Optionnel) Clés API France Travail

Pour activer France Travail :
1. Créez un compte sur https://francetravail.io
2. Créez une application et copiez `client_id` et `client_secret`
3. Ajoutez-les dans votre fichier `.env` :

```
FRANCE_TRAVAIL_CLIENT_ID=votre_id
FRANCE_TRAVAIL_CLIENT_SECRET=votre_secret
```

---

## Utilisation

### Tester la configuration (sans notifications)

```bash
python main.py --test
```

### Lancer une recherche

```bash
python main.py
```

### Lancer en mode continu (recommandé)

```bash
python main.py --loop
```

Le programme recherchera automatiquement toutes les 60 minutes (modifiable dans `config.yaml`).

### Voir l'historique des offres trouvées

```bash
python main.py --history
```

---

## Structure du projet

```
FC_chomage/
├── config.yaml          ← Vos critères de recherche (à modifier)
├── .env                 ← Vos clés secrètes (à créer)
├── main.py              ← Script principal
├── requirements.txt     ← Dépendances Python
├── jobs.db              ← Base de données (créée automatiquement)
├── scrapers/            ← Modules de collecte d'offres
├── notifiers/           ← Modules de notification (Discord)
├── database/            ← Gestion de la base de données
└── utils/               ← Fonctions utilitaires
```

---

## Notifications Discord

Chaque nouvelle offre trouvée génère une notification avec :
- Le titre du poste
- L'entreprise et la localisation
- Le type de contrat et le salaire (si disponible)
- Un score de pertinence (⭐ à ⭐⭐⭐⭐⭐)
- Un lien direct vers l'offre

---

## Dépannage

| Problème | Solution |
|----------|----------|
| Aucune offre trouvée | Vérifiez votre connexion et vos mots-clés |
| Notifications non reçues | Vérifiez l'URL webhook dans `.env` |
| France Travail erreur 401 | Vérifiez `client_id` et `client_secret` |
| Trop d'offres non pertinentes | Ajoutez des mots dans `exclusions` |
