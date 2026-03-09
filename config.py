"""
============================================================
  config.py  –  Configuration centralisée du robot XTB
============================================================
Les valeurs sont lues depuis le fichier .env (ou les variables
d'environnement système).  Aucun identifiant n'est stocké
directement dans le code source.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Charger le fichier .env situé à la racine du projet
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")


# ── Identifiants XTB ─────────────────────────────────────────
XTB_USER_ID: str = os.getenv("XTB_USER_ID", "")
XTB_PASSWORD: str = os.getenv("XTB_PASSWORD", "")
XTB_MODE: str = os.getenv("XTB_MODE", "demo")          # "demo" ou "real"

# ── Actif à trader ────────────────────────────────────────────
SYMBOL: str = os.getenv("SYMBOL", "EURUSD")

# ── Paramètres de la stratégie (moyennes mobiles) ─────────────
MA_FAST: int = int(os.getenv("MA_FAST", "20"))          # Période MA courte
MA_SLOW: int = int(os.getenv("MA_SLOW", "50"))          # Période MA longue

# ── Gestion du risque ─────────────────────────────────────────
VOLUME: float = float(os.getenv("VOLUME", "0.01"))      # Taille du lot
STOP_LOSS_PIPS: int = int(os.getenv("STOP_LOSS_PIPS", "50"))
TAKE_PROFIT_PIPS: int = int(os.getenv("TAKE_PROFIT_PIPS", "100"))

# ── Boucle principale ────────────────────────────────────────
LOOP_INTERVAL: int = int(os.getenv("LOOP_INTERVAL", "30"))  # secondes

# ── Paper trading (simulation) ────────────────────────────────
PAPER_TRADING: bool = os.getenv("PAPER_TRADING", "true").lower() == "true"

# ── Adresses des serveurs (xAPI) ──────────────────────────────
# IMPORTANT : L'API officielle XTB (ws.xtb.com) a été désactivée
# le 14 mars 2025.  La même API est disponible chez X Open Hub,
# filiale de XTB, via le host "ws.xapi.pro".
#
# Pour utiliser X Open Hub :
#   1. Créez un compte démo sur https://xopenhub.pro/try-demo/
#   2. Utilisez le login (numéro) et mot de passe de ce compte
#   3. Gardez XTB_HOST=ws.xapi.pro (défaut)
#
# Si XTB réactive un jour son API publique, changez simplement
# XTB_HOST=ws.xtb.com dans votre .env.
# ──────────────────────────────────────────────────────────────
XTB_HOST: str = os.getenv("XTB_HOST", "ws.xapi.pro")

SERVER_MAIN: str = f"wss://{XTB_HOST}/{XTB_MODE}"
SERVER_STREAM: str = f"wss://{XTB_HOST}/{XTB_MODE}Stream"

# ── Timeframe pour les bougies (en minutes) ──────────────────
# 1, 5, 15, 30, 60, 240, 1440, 10080, 43200
CANDLE_PERIOD: int = int(os.getenv("CANDLE_PERIOD", "60"))  # 60 minutes (H1)
