# Sonomètre lumineux 🔊

Système de monitoring sonore temps réel pour réfectoire, salle d'activité ou tout espace collectif. Un bandeau LED WS2812B change de couleur selon le niveau sonore ambiant, piloté par un Raspberry Pi 3B+, avec une interface web de supervision et de configuration.

![Badge Python](https://img.shields.io/badge/Python-3.x-blue) ![Badge Flask](https://img.shields.io/badge/Flask-2.x-lightgrey) ![Badge RPi](https://img.shields.io/badge/Raspberry%20Pi-3B%2B-red)

---

## Fonctionnalités

- Bandeau LED WS2812B progressif vert → orange → rouge selon le niveau sonore
- Lissage attack/release asymétrique (montée rapide, descente douce)
- Alerte rouge : temporisation avant déclenchement + durée minimale garantie
- 4 animations de démarrage configurables (vague, respiration, arc-en-ciel, compteur)
- Interface web responsive (Dashboard, Historique, Statut, Config)
- Jauge temps réel + graphes ApexCharts avec sélecteur de période
- Page publique "réfectoire" (feu tricolore animé, alerte sonore Web Audio API)
- Configuration complète via interface web (seuils, réactivité, LEDs, animations)
- Export CSV, sauvegarde ZIP complète
- Monitoring uptime service (grille 7 jours)
- Éditeur de fichiers en ligne

---

## Matériel requis

| Composant | Référence | Quantité |
|---|---|---|
| Raspberry Pi 3B+ | - | 1 |
| Bandeau LED WS2812B 5V | ex. Amazon B01CDTED80 (60 LEDs/m) | 1m |
| Microphone USB | tout micro USB compatible Linux | 1 |
| Alimentation 5V 2A | USB ou jack | 1 |
| Câbles Dupont femelle-femelle | - | 2 |
| Connecteurs Wago 221 (3 ou 5 entrées) | - | 2 |

> Le bandeau WS2812B doit être alimenté en **5V uniquement**. Ne jamais utiliser une alimentation 12V.

---

## Schéma de câblage

```
RPi broche 12 (GPIO 18) ----[câble Dupont]---- Fil VERT bandeau (DATA)

RPi broche 9 (GND)  -----+
                          |
Alimentation (fil GND) ---+---- Wago GND ----+---- Fil BLANC bandeau (GND)

Alimentation (fil +5V) ---+---- Wago +5V ----+---- Fil ROUGE bandeau (V+)
```

### Détail des connexions

| Fil bandeau | Destination |
|---|---|
| Fil rouge (V+) | Wago "+5V" |
| Fil blanc (GND) | Wago "GND" |
| Fil vert (DATA) | Broche 12 du RPi (GPIO 18) — câble Dupont direct |

| Alimentation USB | Destination |
|---|---|
| Fil rouge (+5V) | Wago "+5V" |
| Fil blanc/noir (GND) | Wago "GND" |

| RPi | Destination |
|---|---|
| Broche 12 (GPIO 18) | Fil vert du bandeau (câble Dupont direct, sans Wago) |
| Broche 9 (GND) | Wago "GND" (câble Dupont) |

> **Important** : le fil DATA ne doit jamais passer par un Wago — connecter directement la broche GPIO 18 au fil DATA du bandeau via un câble Dupont.

### Côté bandeau

Brancher côté **Din** (Data In). Le sens est indiqué par une flèche ou l'inscription "Din/Do" sur le circuit imprimé.

---

## Prérequis logiciels

Testé sur **Raspberry Pi OS Bookworm (64-bit)**.

```bash
sudo apt update && sudo apt install -y python3-pip python3-dev
```

Les dépendances Python (`requirements.txt`) sont installées à l'étape [Installation](#installation).

### Configuration audio obligatoire

Désactiver l'audio onboard du RPi pour éviter les conflits avec le driver PWM des LEDs :

```bash
sudo nano /boot/firmware/config.txt
```

Modifier ou ajouter :
```
dtparam=audio=off
```

Redémarrer après modification.

---

## Installation

Tous les fichiers (scripts Python, templates, config) vivent dans **un seul dossier** sur le Raspberry Pi — `sonometer.py`, `app.py` et `uptime_check.py` génèrent `sonometer.db`/`config.json` à côté d'eux-mêmes, quel que soit l'endroit où ce dossier est cloné.

```bash
# Cloner le repo directement à l'emplacement de déploiement, ex. /home/pi/sonometer
git clone https://github.com/TON_USER/sonometer.git /home/pi/sonometer
cd /home/pi/sonometer
pip3 install -r requirements.txt --break-system-packages
```

### Configurer les services systemd

Créer `/etc/systemd/system/sonometer.service` (adapter le chemin `/home/pi/sonometer` si besoin) :

```ini
[Unit]
Description=Sonometre lumineux
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/sonometer/sonometer.py
Restart=always
User=root
WorkingDirectory=/home/pi/sonometer

[Install]
WantedBy=multi-user.target
```

Créer `/etc/systemd/system/webapp.service` :

```ini
[Unit]
Description=Sonometer Web App
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/sonometer/app.py
Restart=always
User=root
WorkingDirectory=/home/pi/sonometer
Environment=FLASK_SECRET_KEY=remplacer-par-une-valeur-generee

[Install]
WantedBy=multi-user.target
```

> Générer une vraie clé secrète avec `python3 -c "import secrets; print(secrets.token_hex(32))"` et la coller dans `Environment=FLASK_SECRET_KEY=...`.

Activer et démarrer :

```bash
sudo systemctl daemon-reload
sudo systemctl enable sonometer webapp
sudo systemctl start sonometer webapp
```

### Configurer le cron uptime

```bash
sudo crontab -e
```

Ajouter :
```
0 * * * * /usr/bin/python3 /home/pi/sonometer/uptime_check.py
```

---

## Configuration initiale

Créer `config.json` à la racine du projet (ou laisser l'application le générer au premier démarrage) :

```json
{
  "db_min": 29,
  "db_orange": 37,
  "db_rouge": 44,
  "db_max": 51,
  "blink_speed": 0.3,
  "username": "admin",
  "password": "sonometer",
  "son_actif": true,
  "son_delai": 5,
  "son_type": "gong",
  "graph_duree": 60,
  "led_count": 60,
  "attack": 0.6,
  "release": 0.08,
  "rouge_duree": 3,
  "rouge_duree_min": 5,
  "startup_anim": "vague"
}
```

> Modifier `username` et `password` avant mise en production.

---

## Accès

| URL | Description |
|---|---|
| `http://IP_DU_RPI:5000` | Interface admin (login requis) |
| `http://IP_DU_RPI:5000/public` | Page publique réfectoire |
| `http://IP_DU_RPI:5000/editor` | Éditeur de fichiers en ligne |

Trouver l'IP du RPi depuis ta box internet, ou via :

```bash
ping noisedetector.local
```

---

## Paramètres de configuration

| Paramètre | Description |
|---|---|
| `db_min` | Seuil de silence — en dessous, aucune LED allumée |
| `db_orange` | Fin de la zone verte / début de l'orange |
| `db_rouge` | Fin de la zone orange / début du rouge + seuil d'alerte |
| `db_max` | Plafond de l'échelle |
| `led_count` | Nombre de LEDs du bandeau |
| `attack` | Réactivité à la montée (0.1 = doux, 1.0 = instantané) |
| `release` | Douceur de la descente (0.02 = lent, 0.5 = rapide) |
| `rouge_duree` | Durée en secondes au-dessus du seuil rouge avant déclenchement de l'alerte |
| `rouge_duree_min` | Durée minimale du clignotement d'alerte une fois déclenché |
| `blink_speed` | Vitesse de clignotement de l'alerte rouge (secondes) |
| `startup_anim` | Animation de démarrage : `vague`, `respiration`, `arcenciel`, `compteur` |

---

## Structure du projet

```
sonometer/
├── sonometer.py              # Script de mesure audio + pilotage LEDs
├── app.py                    # Serveur Flask (routes, API, config)
├── uptime_check.py           # Script cron vérification uptime horaire
├── config.json                # Configuration (généré au 1er démarrage, non versionné)
├── sonometer.db                # Base SQLite des mesures (générée à l'exécution, non versionnée)
├── requirements.txt
└── templates/
    ├── index.html             # Dashboard temps réel
    ├── history.html           # Historique et statistiques
    ├── status.html            # Statut système + grille uptime
    ├── config.html            # Interface de configuration
    ├── public.html             # Page publique réfectoire
    ├── login.html               # Page de connexion
    └── editor.html               # Éditeur de fichiers en ligne
```

---

## Stack technique

| Couche | Technologie |
|---|---|
| Langage | Python 3 |
| Audio | sounddevice, numpy |
| LEDs | rpi-ws281x |
| Backend | Flask |
| Base de données | SQLite3 |
| Frontend | HTML/CSS/JS vanilla, ApexCharts 3.45.2 |

---

## Dépannage

**Le bandeau ne s'allume pas**
- Vérifier que `dtparam=audio=off` est bien dans `/boot/firmware/config.txt`
- Vérifier que le fil DATA est sur la broche 12 (GPIO 18) côté RPi, et sur Din côté bandeau
- Tester avec le bouton "Tester" dans Config (nécessite d'être connecté)

**Le service ne démarre pas**
```bash
sudo journalctl -u sonometer.service -n 50 --no-pager
sudo python3 /home/pi/sonometer/sonometer.py   # test manuel pour voir l'erreur
```

**Le micro n'est pas détecté**
```bash
python3 -c "import sounddevice; print(sounddevice.query_devices())"
```

**Impossible d'accéder à l'interface web**
```bash
sudo systemctl status webapp.service --no-pager
```

---

## Licence

MIT

---

## Auteur

Projet développé pour la gestion sonore d'un centre de vacances.
