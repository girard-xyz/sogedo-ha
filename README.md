# Sogedo Water for Home Assistant

Reads your daily water consumption from [mon-compte.sogedo.fr](https://mon-compte.sogedo.fr) and feeds it into the Home Assistant Energy Dashboard.

[![Open your Home Assistant instance and show the HACS repository.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=girard-xyz&repository=sogedo-ha&category=integration)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

---

## English / Anglais

### Features

- **Daily consumption** sensor (`sensor.sogedo_water_daily`) — water used on the last completed day (J-1), in m³.
- **Cumulative consumption** sensor (`sensor.sogedo_water_cumulative`) — current total meter index, `total_increasing`.
- **Water history** (`sensor.sogedo_water_consumption`) — a statistics-only history series backfilled with your full consumption history. This is the Energy Dashboard **mains water** source.
- **Water cost history** (`sensor.sogedo_water_cost`) — a statistics-only cost series (consumption × your Energy Dashboard water price, read automatically at backfill time). Set it as the water source **Coût** (`stat_cost`).
- **Refresh history** button (`button.sogedo_actualiser_l_historique`) — re-runs the backfill on demand (idempotent, safe to press any time).
- Backfills your full water history on first setup (best-effort; a failure never breaks the integration).
- Updates every 6 hours (Sogedo publishes data daily).
- Auto-triggers an in-place re-auth if the token expires (entities are preserved).

### Requirements

- Home Assistant with [HACS](https://hacs.xyz)
- A Sogedo online-account login

### Installation

1. **HACS** → ⋯ (Custom repositories) → add `https://github.com/girard-xyz/sogedo-ha` → category **Integration** → install. (Or use the **Add repository** button at the top of this page.)
2. **Restart Home Assistant.**
3. **Settings → Devices & Services → Add Integration → Sogedo Water.**
4. **Authorize:** click the link, log in to Sogedo, copy the `code=...` value from the redirect URL, and paste it back.

### Entities

| Entity | Purpose |
|---|---|
| `sensor.sogedo_water_daily` | water used on the last completed day (J-1), m³ |
| `sensor.sogedo_water_cumulative` | current meter index (`total_increasing`) |
| `sensor.sogedo_water_consumption` | history series (statistics-only) — **Energy Dashboard water source** |
| `sensor.sogedo_water_cost` | cost history series (statistics-only) — **Energy Dashboard Coût source** |
| `button.sogedo_actualiser_l_historique` | re-run the backfill |

> Note: sensor entity IDs are localized to your Home Assistant language (e.g. French → `sensor.consommation_journaliere`, `sensor.consommation_cumulee`). The two history statistics (`sensor.sogedo_water_consumption`, `sensor.sogedo_water_cost`) are fixed.

### Energy Dashboard setup

1. **Settings → Energy → Water sources → Add** (or edit the existing one).
2. **Mains water** → select `sensor.sogedo_water_consumption`.
3. Set the **Coût (cost)** statistic → `sensor.sogedo_water_cost`.
4. Set the **price** (€/m³) for the source.

The backfill writes running cumulatives of the daily consumption and cost, so every day shows its real consumption and cost — including backfilled history. The water price is read from your Energy Dashboard water source config at backfill time. After changing the price, press the **Actualiser l'historique** button to recompute the cost history.

> The water **graph** card shows consumption only; the **cost** appears in the cost breakdown / flow.

### Troubleshooting

- **"Sogedo backfill failed; skipping"** in the logs → open the log entry for the full traceback (usually a transient API/network issue; press the button to retry).
- **Token expired** (HA off for > 24 h) → Home Assistant shows a **re-auth** prompt (the entry shows *Reconfigurer* / *Connexion requise*). Re-authenticate in place — entities and dashboard settings are preserved.
- **No new data** → check the sensor's last update; Sogedo publishes the previous day (J-1).

### Notes

Sogedo uses Azure AD B2C and disables device-code and username/password (ROPC) flows, so setup requires the one-time interactive authorization-code flow described above. Your Sogedo password is never stored — only a refresh token in Home Assistant's config entry.

---

## Français / French

### Fonctionnalités

- **Consommation journalière** (`sensor.consommation_journaliere`) — eau consommée le dernier jour complet (J-1), en m³.
- **Consommation cumulée** (`sensor.consommation_cumulee`) — index actuel du compteur, `total_increasing`.
- **Historique de consommation** (`sensor.sogedo_water_consumption`) — série d'historique (statistiques uniquement), rétro-remplie avec toute votre consommation. C'est la source **Eau du réseau** du tableau de bord Énergie.
- **Historique de coût** (`sensor.sogedo_water_cost`) — série de coût (consommation × prix configuré dans Énergie, lu automatiquement). À renseigner comme statistique **Coût** (`stat_cost`).
- **Actualiser l'historique** (`button.actualiser_l_historique`) — relance le rétro-remplissage à la demande (idempotent, sans risque).
- Rétro-remplit tout l'historique au premier démarrage (non bloquant en cas d'échec).
- Mise à jour toutes les 6 heures (Sogedo publie les données quotidiennement).
- Ré-authentification automatique si le jeton expire (les entités sont conservées).

### Prérequis

- Home Assistant avec [HACS](https://hacs.xyz)
- Un compte Sogedo en ligne

### Installation

1. **HACS** → ⋯ (Dépôts personnalisés) → ajouter `https://github.com/girard-xyz/sogedo-ha` → catégorie **Intégration** → installer. (Ou utiliser le bouton **Add repository** en haut de cette page.)
2. **Redémarrer Home Assistant.**
3. **Paramètres → Périphériques et services → Ajouter une intégration → Sogedo Water.**
4. **Autoriser :** cliquer sur le lien, se connecter à Sogedo, copier la valeur `code=...` de l'URL de redirection et la coller.

### Entités

| Entité | Rôle |
|---|---|
| `sensor.consommation_journaliere` | eau consommée le dernier jour complet (J-1), m³ |
| `sensor.consommation_cumulee` | index actuel du compteur (`total_increasing`) |
| `sensor.sogedo_water_consumption` | historique (statistiques) — **source Eau du tableau de bord Énergie** |
| `sensor.sogedo_water_cost` | historique de coût (statistiques) — **source Coût du tableau de bord Énergie** |
| `button.actualiser_l_historique` | relance le rétro-remplissage |

> Remarque : les identifiants des capteurs sont localisés selon la langue de Home Assistant (ex. anglais → `sensor.sogedo_water_daily`). Les deux statistiques d'historique (`sensor.sogedo_water_consumption`, `sensor.sogedo_water_cost`) sont fixes.

### Configuration du tableau de bord Énergie

1. **Paramètres → Énergie → Sources d'eau → Ajouter** (ou modifier).
2. **Eau du réseau** → sélectionner `sensor.sogedo_water_consumption`.
3. Renseigner la statistique **Coût** → `sensor.sogedo_water_cost`.
4. Renseigner le **prix** (€/m³) de la source.

Le rétro-remplissage écrit des cumuls de consommation et de coût, si bien que chaque jour affiche sa consommation et son coût réels — y compris l'historique. Le prix est lu depuis votre configuration Énergie au moment du rétro-remplissage. Après un changement de prix, appuyez sur **Actualiser l'historique** pour recalculer le coût.

> Le graphique **eau** n'affiche que la consommation ; le **coût** apparaît dans le détail des coûts / le flux.

### Dépannage

- **« Sogedo backfill failed; skipping »** dans les journaux → ouvrir l'entrée pour la trace complète (souvent un problème API/réseau passager ; relancer via le bouton).
- **Jeton expiré** (HA éteint plus de 24 h) → Home Assistant affiche une invite de **ré-authentification** (l'entrée montre *Reconfigurer* / *Connexion requise*). Ré-authentifiez sur place — les entités et les réglages Énergie sont conservés.
- **Pas de nouvelles données** → vérifier la dernière mise à jour du capteur ; Sogedo publie la veille (J-1).

### Notes

Sogedo utilise Azure AD B2C et désactive les flux device-code et identifiant/mot de passe (ROPC) : l'installation nécessite donc le flux interactif d'autorisation décrit ci-dessus. Votre mot de passe Sogedo n'est jamais stocké — seul un jeton d'actualisation est conservé dans la configuration de l'intégration.