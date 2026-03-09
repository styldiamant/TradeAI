"""
============================================================
  market_simulator.py  –  Simulateur de marché offline
============================================================
Génère des prix et bougies réalistes sans aucune connexion API.
Utilise un mouvement brownien géométrique (random walk) pour
simuler le comportement d'un actif financier.

Permet de tester le robot sans compte broker.
============================================================
"""

import time
import math
import random
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("SIMULATOR")

# Prix de départ par défaut selon le symbole
_DEFAULT_PRICES = {
    "EURUSD": 1.0850,
    "GBPUSD": 1.2650,
    "USDJPY": 149.50,
    "GASOLINE": 2.05,
    "GOLD": 2180.0,
    "BITCOIN": 62500.0,
    "US500": 5250.0,
    "DE40": 18200.0,
}

# Précision (nombre de décimales) par symbole
_PRECISIONS = {
    "EURUSD": 5,
    "GBPUSD": 5,
    "USDJPY": 3,
    "GASOLINE": 4,
    "GOLD": 2,
    "BITCOIN": 1,
    "US500": 1,
    "DE40": 1,
}


class MarketSimulator:
    """
    Simulateur de marché qui génère des prix et bougies réalistes.
    Remplace l'API XTB quand on n'a pas de compte.
    """

    def __init__(self, symbol: str = "EURUSD", volatility: float = 0.0002):
        """
        Paramètres :
            symbol     – Symbole simulé (ex. "EURUSD")
            volatility – Volatilité par tick (écart-type du mouvement)
                         0.0002 ≈ réaliste pour EURUSD en 5 min
        """
        self.symbol = symbol
        self.volatility = volatility
        self.precision = _PRECISIONS.get(symbol, 5)
        self.spread = 0.00015 if self.precision >= 4 else 0.5

        # Prix initial
        self._mid_price = _DEFAULT_PRICES.get(symbol, 1.0850)
        self._candle_history: list[dict] = []
        self._is_connected = False

        # Générer un historique initial de bougies
        self._generate_initial_history(count=100)

    def _generate_initial_history(self, count: int):
        """Génère `count` bougies historiques à partir du prix de départ."""
        price = self._mid_price * 0.998  # démarrer un peu en dessous
        now = datetime.now()
        start_time = now - timedelta(minutes=count * 5)

        for i in range(count):
            candle_time = start_time + timedelta(minutes=i * 5)
            ctm = int(candle_time.timestamp() * 1000)

            # Mouvement brownien pour générer OHLC
            open_price = price
            moves = [random.gauss(0, self.volatility) for _ in range(20)]
            cumulative = [open_price]
            for m in moves:
                cumulative.append(cumulative[-1] * (1 + m))

            high_price = max(cumulative)
            low_price = min(cumulative)
            close_price = cumulative[-1]

            candle = {
                "ctm": ctm,
                "open": round(open_price, self.precision),
                "close": round(close_price, self.precision),
                "high": round(high_price, self.precision),
                "low": round(low_price, self.precision),
                "vol": random.randint(50, 500),
            }
            self._candle_history.append(candle)
            price = close_price

        self._mid_price = price
        logger.debug("Historique initial généré : %d bougies", count)

    def _tick(self):
        """Fait avancer le prix d'un pas (mouvement aléatoire)."""
        change = random.gauss(0, self.volatility)
        self._mid_price *= (1 + change)
        self._mid_price = round(self._mid_price, self.precision)

    # ── Interface identique à XTBClient ───────────────────────

    def connect(self) -> bool:
        """Simule une connexion réussie."""
        logger.info("✅ [OFFLINE] Simulateur de marché connecté (pas d'API)")
        self._is_connected = True
        return True

    def disconnect(self):
        """Simule une déconnexion."""
        self._is_connected = False
        logger.info("[OFFLINE] Simulateur déconnecté.")

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def get_current_price(self, symbol: str) -> dict:
        """Retourne un prix bid/ask simulé."""
        self._tick()
        half_spread = self.spread / 2
        bid = round(self._mid_price - half_spread, self.precision)
        ask = round(self._mid_price + half_spread, self.precision)
        return {
            "bid": bid,
            "ask": ask,
            "spread": round(self.spread, self.precision),
            "pip": 4 if self.precision >= 4 else max(0, self.precision - 1),
        }

    def get_candles(self, symbol: str, period: int, count: int = 100) -> list[dict]:
        """
        Retourne les bougies historiques simulées + génère une nouvelle
        bougie à chaque appel pour simuler le passage du temps.
        """
        # Générer une nouvelle bougie
        now = datetime.now()
        ctm = int(now.timestamp() * 1000)
        open_price = self._mid_price

        moves = [random.gauss(0, self.volatility) for _ in range(20)]
        cumulative = [open_price]
        for m in moves:
            cumulative.append(cumulative[-1] * (1 + m))

        close_price = cumulative[-1]
        self._mid_price = close_price

        new_candle = {
            "ctm": ctm,
            "open": round(open_price, self.precision),
            "close": round(close_price, self.precision),
            "high": round(max(cumulative), self.precision),
            "low": round(min(cumulative), self.precision),
            "vol": random.randint(50, 500),
        }
        self._candle_history.append(new_candle)

        # Garder maximum 500 bougies en mémoire
        if len(self._candle_history) > 500:
            self._candle_history = self._candle_history[-500:]

        # Retourner les dernières `count` bougies
        return self._candle_history[-count:]

    def get_symbol(self, symbol: str) -> dict:
        """Retourne des infos simulées sur le symbole."""
        return {
            "symbol": symbol,
            "bid": self._mid_price,
            "ask": self._mid_price + self.spread,
            "spreadRaw": self.spread,
            "pipsPrecision": 4 if self.precision >= 4 else max(0, self.precision - 1),
        }

    def open_trade(self, **kwargs) -> dict:
        """Simule l'ouverture d'un trade (ne fait rien en mode offline)."""
        return {"order": random.randint(10000, 99999)}

    def close_trade(self, **kwargs) -> dict:
        """Simule la fermeture d'un trade."""
        return {"order": kwargs.get("order_id", 0)}

    def get_open_trades(self) -> list[dict]:
        return []

    def ping(self):
        pass
