"""
============================================================
  real_data.py  –  Fournisseur de données de marché RÉELLES
============================================================
Combine 3 sources gratuites pour des prix en temps réel :
  • Yahoo Finance (yfinance)  → Forex, Indices, Matières, Crypto
  • CoinGecko API             → Crypto (Bitcoin, etc.)
  • ExchangeRate API          → Forex backup

Même interface que MarketSimulator :
  provider.connect()
  provider.get_current_price(symbol)
  provider.get_candles(symbol, period, count)
============================================================
"""

import time
import logging
import threading
from datetime import datetime, timedelta
import calendar

import requests
import yfinance as yf
import pandas as pd
import numpy as np

logger = logging.getLogger("REAL_DATA")

# ── Contrats Futures actifs ───────────────────────────────────
# Les commodités utilisent des contrats mensuels. Yahoo "=F" est le contrat
# continu mais il a des sauts de rollover. XTB utilise le contrat actif.
# Codes mois futures : F=Jan, G=Feb, H=Mar, J=Apr, K=May, M=Jun,
#                      N=Jul, Q=Aug, U=Sep, V=Oct, X=Nov, Z=Dec
_FUTURES_MONTH_CODES = 'FGHJKMNQUVXZ'

def _get_active_contract(base_code: str, exchange: str = "NYM") -> str | None:
    """
    Essaie de trouver le contrat futures actif le plus proche.
    Ex: base_code='RB', exchange='NYM' → 'RBJ26.NYM' (Avril 2026)
    Retourne le ticker Yahoo ou None si échec.
    """
    now = datetime.now()
    # Essayer les 3 prochains mois
    for offset in range(3):
        target = now + timedelta(days=30 * offset)
        month_idx = target.month - 1  # 0-based
        year_short = target.year % 100
        code = _FUTURES_MONTH_CODES[month_idx]
        ticker = f"{base_code}{code}{year_short}.{exchange}"
        try:
            t = yf.Ticker(ticker)
            fi = t.fast_info
            price = fi.get('lastPrice') or fi.get('last_price')
            if price and price > 0:
                logger.info("✅ Contrat actif trouvé : %s (prix=%.4f)", ticker, price)
                return ticker
        except Exception:
            pass
    return None

# Cache des contrats actifs (pas besoin de chercher à chaque appel)
_active_contracts_cache = {}
_active_contracts_lock = threading.Lock()

def _resolve_futures_ticker(symbol: str, default_ticker: str) -> str:
    """
    Résout le ticker Yahoo pour un contrat futures.
    Essaie d'abord le contrat actif, sinon retombe sur le contrat continu (=F).
    """
    with _active_contracts_lock:
        if symbol in _active_contracts_cache:
            ts, ticker = _active_contracts_cache[symbol]
            # Cache 1h
            if time.time() - ts < 3600:
                return ticker

    # Mapping symbole → code de base + exchange
    futures_map = {
        "GASOLINE":  ("RB", "NYM"),
        "OIL":       ("CL", "NYM"),
        "BRENT":     ("BZ", "NYM"),
        "NATGAS":    ("NG", "NYM"),
        "GOLD":      ("GC", "CMX"),
        "SILVER":    ("SI", "CMX"),
        "COPPER":    ("HG", "CMX"),
        "PLATINUM":  ("PL", "NYM"),
        "PALLADIUM": ("PA", "NYM"),
        "WHEAT":     ("ZW", "CBT"),
        "CORN":      ("ZC", "CBT"),
        "SOYBEAN":   ("ZS", "CBT"),
        "COTTON":    ("CT", "NYB"),
        "COFFEE":    ("KC", "NYB"),
        "SUGAR":     ("SB", "NYB"),
        "COCOA":     ("CC", "NYB"),
    }

    if symbol not in futures_map:
        return default_ticker

    base, exch = futures_map[symbol]
    active = _get_active_contract(base, exch)
    result = active or default_ticker

    with _active_contracts_lock:
        _active_contracts_cache[symbol] = (time.time(), result)

    return result

# ── Mapping symbole interne → ticker Yahoo Finance ───────────
YAHOO_TICKERS = {
    # ── Forex ──
    "EURUSD":   "EURUSD=X",
    "GBPUSD":   "GBPUSD=X",
    "USDJPY":   "USDJPY=X",
    "USDCHF":   "USDCHF=X",
    "AUDUSD":   "AUDUSD=X",
    "USDCAD":   "USDCAD=X",
    "NZDUSD":   "NZDUSD=X",
    "EURGBP":   "EURGBP=X",
    "EURJPY":   "EURJPY=X",
    "GBPJPY":   "GBPJPY=X",
    "EURCHF":   "EURCHF=X",
    "AUDJPY":   "AUDJPY=X",
    "CADJPY":   "CADJPY=X",
    # ── Indices ──
    "US500":    "^GSPC",       # S&P 500
    "US100":    "^IXIC",       # Nasdaq 100
    "US30":     "^DJI",        # Dow Jones 30
    "DE40":     "^GDAXI",      # DAX 40
    "UK100":    "^FTSE",       # FTSE 100
    "FR40":     "^FCHI",       # CAC 40
    "JP225":    "^N225",       # Nikkei 225
    "EU50":     "^STOXX50E",   # Euro Stoxx 50
    "AU200":    "^AXJO",       # ASX 200
    "HK50":     "^HSI",        # Hang Seng
    "CN50":     "000001.SS",   # SSE Composite
    "VIX":      "^VIX",        # Volatility Index
    # ── Matières premières ──
    "GOLD":     "GC=F",        # Gold Futures
    "SILVER":   "SI=F",        # Silver Futures
    "GASOLINE": "RB=F",        # RBOB Gasoline Futures
    "OIL":      "CL=F",        # WTI Crude Oil
    "BRENT":    "BZ=F",        # Brent Crude Oil
    "NATGAS":   "NG=F",        # Natural Gas
    "COPPER":   "HG=F",        # Copper
    "PLATINUM": "PL=F",        # Platinum
    "PALLADIUM": "PA=F",       # Palladium
    "WHEAT":    "ZW=F",        # Wheat
    "CORN":     "ZC=F",        # Corn
    "SOYBEAN":  "ZS=F",        # Soybean
    "COTTON":   "CT=F",        # Cotton
    "COFFEE":   "KC=F",        # Coffee
    "SUGAR":    "SB=F",        # Sugar
    "COCOA":    "CC=F",        # Cocoa
    # ── Crypto ──
    "BITCOIN":  "BTC-USD",
    "ETHEREUM": "ETH-USD",
    "SOLANA":   "SOL-USD",
    "XRP":      "XRP-USD",
    "CARDANO":  "ADA-USD",
    "DOGECOIN": "DOGE-USD",
    "POLKADOT": "DOT-USD",
    "AVAX":     "AVAX-USD",
    "CHAINLINK": "LINK-USD",
    "MATIC":    "MATIC-USD",
    "LITECOIN": "LTC-USD",
    "BNB":      "BNB-USD",
    # ── Actions US ──
    "APPLE":    "AAPL",
    "TESLA":    "TSLA",
    "NVIDIA":   "NVDA",
    "MICROSOFT": "MSFT",
    "AMAZON":   "AMZN",
    "GOOGLE":   "GOOGL",
    "META":     "META",
    "NETFLIX":  "NFLX",
    "AMD":      "AMD",
    "INTEL":    "INTC",
    "COINBASE": "COIN",
    # ── Actions EU ──
    "LVMH":     "MC.PA",
    "AIRBUS":   "AIR.PA",
    "SAP":      "SAP.DE",
    "SIEMENS":  "SIE.DE",
    "TOTALENERGIES": "TTE.PA",
}

# Multiplicateur de prix (pour aligner avec la convention XTB)
# Ex: Yahoo donne GASOLINE en $/gallon (~2.74), XTB en cents/gallon (~274)
PRICE_MULTIPLIER = {
    "GASOLINE": 100,
}

# Mapping CoinGecko pour les cryptos
COINGECKO_IDS = {
    "BITCOIN":   "bitcoin",
    "ETHEREUM":  "ethereum",
    "SOLANA":    "solana",
    "XRP":       "ripple",
    "CARDANO":   "cardano",
    "DOGECOIN":  "dogecoin",
    "POLKADOT":  "polkadot",
    "AVAX":      "avalanche-2",
    "CHAINLINK": "chainlink",
    "MATIC":     "matic-network",
    "LITECOIN":  "litecoin",
    "BNB":       "binancecoin",
}

# Intervalle yfinance selon la période en minutes
YF_INTERVAL_MAP = {
    1: "1m", 5: "5m", 15: "15m", 30: "30m", 60: "1h", 240: "1h", 1440: "1d",
}

# ── Cache pour limiter les appels API ────────────────────────
_cache = {}
_cache_lock = threading.Lock()
CACHE_TTL_PRICE = 2        # secondes – prix courant (temps réel)
CACHE_TTL_CANDLES = 15     # secondes – bougies historiques (refresh fréquent pour rester à jour)


def _cache_get(key: str, ttl: int):
    """Retourne la valeur en cache si < ttl secondes, sinon None."""
    with _cache_lock:
        if key in _cache:
            ts, val = _cache[key]
            if time.time() - ts < ttl:
                return val
    return None


def _cache_set(key: str, val):
    with _cache_lock:
        _cache[key] = (time.time(), val)


# ── Volatilité typique par actif (tick-par-tick) ────────────
TICK_VOLATILITY = {
    # Forex
    "EURUSD": 0.000008, "GBPUSD": 0.000010, "USDJPY": 0.008,
    "USDCHF": 0.000008, "AUDUSD": 0.000008, "USDCAD": 0.000008,
    "NZDUSD": 0.000008, "EURGBP": 0.000008, "EURJPY": 0.008,
    "GBPJPY": 0.010, "EURCHF": 0.000008, "AUDJPY": 0.008,
    "CADJPY": 0.008,
    # Indices
    "US500": 0.40, "US100": 0.80, "US30": 3.0, "DE40": 1.2,
    "UK100": 0.8, "FR40": 0.6, "JP225": 15.0, "EU50": 0.5,
    "AU200": 0.6, "HK50": 8.0, "CN50": 3.0, "VIX": 0.05,
    # Matières
    "GOLD": 0.15, "SILVER": 0.01, "GASOLINE": 0.08, "OIL": 0.03,
    "BRENT": 0.03, "NATGAS": 0.005, "COPPER": 0.003,
    "PLATINUM": 0.30, "PALLADIUM": 0.80,
    "WHEAT": 0.20, "CORN": 0.10, "SOYBEAN": 0.20,
    "COTTON": 0.05, "COFFEE": 0.15, "SUGAR": 0.01, "COCOA": 5.0,
    # Crypto
    "BITCOIN": 8.0, "ETHEREUM": 1.5, "SOLANA": 0.08, "XRP": 0.001,
    "CARDANO": 0.0005, "DOGECOIN": 0.0002, "POLKADOT": 0.01,
    "AVAX": 0.02, "CHAINLINK": 0.01, "MATIC": 0.001,
    "LITECOIN": 0.10, "BNB": 0.30,
    # Actions
    "APPLE": 0.10, "TESLA": 0.30, "NVIDIA": 0.25, "MICROSOFT": 0.15,
    "AMAZON": 0.15, "GOOGLE": 0.12, "META": 0.20, "NETFLIX": 0.25,
    "AMD": 0.15, "INTEL": 0.05, "COINBASE": 0.20,
    "LVMH": 0.50, "AIRBUS": 0.15, "SAP": 0.10, "SIEMENS": 0.10,
    "TOTALENERGIES": 0.05,
}


class LivePriceTicker:
    """
    Générateur de prix en temps réel.
    Utilise le prix API comme ancre et applique des micro-mouvements
    réalistes entre les mises à jour (random walk autour de la base).
    Le prix se resynchronise avec l'API toutes les API_REFRESH secondes.
    """
    API_REFRESH = 10   # Resync avec l'API source toutes les 10s (temps réel)

    def __init__(self, symbol: str):
        self.symbol = symbol
        self._base_price = 0.0         # dernier prix API
        self._current_price = 0.0      # prix live qui bouge
        self._last_api_fetch = 0.0     # timestamp du dernier appel API
        self._tick_vol = TICK_VOLATILITY.get(symbol, 0.0001)
        self._trend = 0.0              # micro-tendance aléatoire
        self._trend_ttl = 0            # durée de la tendance
        self._lock = threading.Lock()
        # Historique des ticks récents pour la "bougie live"
        self._live_ticks: list[float] = []
        self._live_candle_start = 0.0

    def set_base_price(self, price: float):
        """Met à jour le prix de base depuis l'API."""
        with self._lock:
            self._base_price = price
            # Si c'est la première fois, on initialise le prix live
            if self._current_price == 0.0:
                self._current_price = price
            self._last_api_fetch = time.time()

    def needs_api_refresh(self) -> bool:
        """Retourne True si on doit re-fetch le prix API."""
        return (time.time() - self._last_api_fetch) > self.API_REFRESH

    def tick(self) -> float:
        """
        Retourne le dernier prix réel de l'API, sans micro-mouvements artificiels.
        """
        with self._lock:
            if self._base_price == 0:
                return 0.0

            self._current_price = self._base_price

            # Enregistrer pour la bougie live (garder 30 ticks max)
            self._live_ticks.append(self._current_price)
            if len(self._live_ticks) > 30:
                self._live_ticks = self._live_ticks[-30:]

            return self._current_price

    def get_live_candle(self, period_minutes: int = 5) -> dict | None:
        """
        Retourne une bougie "live" construite à partir des ticks récents
        pour la période en cours (filtrés par le bucket temporel actuel).
        """
        with self._lock:
            if not self._live_ticks or self._base_price == 0:
                return None
            now_ms = int(time.time() * 1000)
            bucket_ms = period_minutes * 60 * 1000
            candle_start = now_ms // bucket_ms * bucket_ms

            # Utiliser le prix courant pour la bougie live
            # (évite les outliers des anciens ticks)
            price = self._current_price
            # Calculer OHLC à partir des ticks récents (dernière minute max)
            recent = self._live_ticks[-60:] if len(self._live_ticks) > 60 else self._live_ticks
            
            # Filtrer les prix aberrants (>5% d'écart avec le prix de base)
            valid = [p for p in recent if abs(p - self._base_price) / self._base_price < 0.05]
            if not valid:
                valid = [price]
            
            return {
                "ctm": candle_start,
                "open": round(valid[0], 6),
                "high": round(max(valid), 6),
                "low": round(min(valid), 6),
                "close": round(price, 6),
                "vol": 0,
                "live": True,
            }


# ── Registre global des tickers ──────────────────────────────
_tickers: dict[str, LivePriceTicker] = {}
_tickers_lock = threading.Lock()


def _get_ticker(symbol: str) -> LivePriceTicker:
    with _tickers_lock:
        if symbol not in _tickers:
            _tickers[symbol] = LivePriceTicker(symbol)
        return _tickers[symbol]


class RealDataProvider:
    """
    Fournisseur de données de marché réelles.
    Même interface que MarketSimulator pour un remplacement direct.
    """

    def __init__(self, symbol: str = "EURUSD"):
        self.default_symbol = symbol
        self._connected = False

    def connect(self):
        """Initialise la connexion (test de connectivité)."""
        logger.info("RealDataProvider initialisé – données de marché réelles")
        self._connected = True

    def disconnect(self):
        self._connected = False

    # ─────────────────────────────────────────────────────────
    #  Prix courant (TEMPS RÉEL via LivePriceTicker)
    # ─────────────────────────────────────────────────────────
    def get_current_price(self, symbol: str = None) -> dict:
        """
        Retourne le prix courant en temps réel : {bid, ask, spread}
        Le LivePriceTicker génère des micro-mouvements entre les refreshs API.
        """
        symbol = symbol or self.default_symbol
        ticker = _get_ticker(symbol)

        # Resync avec l'API source si nécessaire
        if ticker.needs_api_refresh():
            api_price = self._fetch_api_price(symbol)
            if api_price is not None:
                ticker.set_base_price(api_price)

        # Générer un tick en temps réel
        live_price = ticker.tick()
        if live_price == 0:
            # Premier appel, pas encore de base → fetch API maintenant
            api_price = self._fetch_api_price(symbol)
            if api_price:
                ticker.set_base_price(api_price)
                live_price = ticker.tick()
            else:
                return {"bid": 0, "ask": 0, "spread": 0}

        spread = self._typical_spread(symbol, live_price)
        bid = round(live_price - spread / 2, 6)
        ask = round(live_price + spread / 2, 6)
        return {"bid": bid, "ask": ask, "spread": round(spread, 6)}

    def _fetch_api_price(self, symbol: str) -> float | None:
        """
        Récupère le prix depuis les APIs externes (Yahoo → CoinGecko → ExchangeRate).
        Retourne un float ou None.
        """
        cache_key = f"api_price_{symbol}"
        cached = _cache_get(cache_key, CACHE_TTL_PRICE)
        if cached:
            return cached

        price = None

        # 1) Yahoo Finance
        result = self._yahoo_price(symbol)
        if result:
            price = (result["bid"] + result["ask"]) / 2

        # 2) CoinGecko fallback pour crypto
        if price is None and symbol in COINGECKO_IDS:
            result = self._coingecko_price(symbol)
            if result:
                price = (result["bid"] + result["ask"]) / 2

        # 3) ExchangeRate fallback pour forex
        if price is None and symbol in ("EURUSD", "GBPUSD", "USDJPY"):
            result = self._exchangerate_price(symbol)
            if result:
                price = (result["bid"] + result["ask"]) / 2

        if price:
            _cache_set(cache_key, price)
        return price

    def _yahoo_price(self, symbol: str) -> dict | None:
        """Prix via Yahoo Finance."""
        default_ticker = YAHOO_TICKERS.get(symbol)
        if not default_ticker:
            return None
        # Pour les futures, utiliser le contrat actif
        ticker_name = _resolve_futures_ticker(symbol, default_ticker)
        try:
            ticker = yf.Ticker(ticker_name)
            # fast_info est plus rapide que info
            fi = ticker.fast_info
            last = fi.get("lastPrice") or fi.get("last_price") or fi.get("regularMarketPrice")

            if last is None:
                # Fallback: télécharger la dernière bougie
                df = yf.download(ticker_name, period="1d", interval="1m",
                                 progress=False, auto_adjust=True)
                if df.empty:
                    df = yf.download(ticker_name, period="5d", interval="5m",
                                     progress=False, auto_adjust=True)
                if df.empty:
                    return None
                last = float(df["Close"].iloc[-1])

            last = float(last)
            # Appliquer le multiplicateur de prix (ex: GASOLINE $/gal → ¢/gal)
            mult = PRICE_MULTIPLIER.get(symbol, 1)
            last *= mult
            # Simuler bid/ask avec un spread réaliste
            spread = self._typical_spread(symbol, last)
            bid = round(last - spread / 2, 6)
            ask = round(last + spread / 2, 6)
            return {"bid": bid, "ask": ask, "spread": round(spread, 6)}

        except Exception as e:
            logger.debug("Yahoo Finance prix %s : %s", symbol, e)
            return None

    def _coingecko_price(self, symbol: str) -> dict | None:
        """Prix via CoinGecko (crypto)."""
        cg_id = COINGECKO_IDS.get(symbol)
        if not cg_id:
            return None
        try:
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd&include_24hr_change=true"
            resp = requests.get(url, timeout=5)
            data = resp.json()
            last = float(data[cg_id]["usd"])
            spread = self._typical_spread(symbol, last)
            bid = round(last - spread / 2, 2)
            ask = round(last + spread / 2, 2)
            return {"bid": bid, "ask": ask, "spread": round(spread, 2)}
        except Exception as e:
            logger.debug("CoinGecko prix %s : %s", symbol, e)
            return None

    def _exchangerate_price(self, symbol: str) -> dict | None:
        """Prix via ExchangeRate API (forex)."""
        try:
            # Extraire les devises (ex: EURUSD → base=EUR, quote=USD)
            base = symbol[:3]
            quote = symbol[3:]
            url = f"https://open.er-api.com/v6/latest/{base}"
            resp = requests.get(url, timeout=5)
            data = resp.json()
            if data.get("result") != "success":
                return None
            rate = float(data["rates"][quote])
            spread = self._typical_spread(symbol, rate)
            bid = round(rate - spread / 2, 6)
            ask = round(rate + spread / 2, 6)
            return {"bid": bid, "ask": ask, "spread": round(spread, 6)}
        except Exception as e:
            logger.debug("ExchangeRate prix %s : %s", symbol, e)
            return None

    def _typical_spread(self, symbol: str, price: float) -> float:
        """Spread typique selon l'actif."""
        spreads = {
            "EURUSD": 0.00015, "GBPUSD": 0.00018, "USDJPY": 0.015,
            "GOLD": 0.50, "GASOLINE": 0.30, "BITCOIN": 15.0,
            "US500": 0.50, "DE40": 1.5,
        }
        return spreads.get(symbol, price * 0.0002)

    # ─────────────────────────────────────────────────────────
    #  Bougies historiques + bougie live
    # ─────────────────────────────────────────────────────────
    def _validate_candles_vs_price(self, symbol: str, candles: list[dict]) -> bool:
        """
        Vérifie que les bougies correspondent bien au bon actif en comparant
        le prix médian des bougies avec le prix courant de l'API.
        Retourne True si les données sont cohérentes.
        """
        if not candles:
            return False

        # Prix médian des bougies
        closes = [c["close"] for c in candles if c["close"] > 0]
        if not closes:
            return False
        median_close = sorted(closes)[len(closes) // 2]

        # Prix courant depuis l'API
        api_price = self._fetch_api_price(symbol)
        if api_price is None or api_price <= 0:
            # Pas de prix de référence → accepter les bougies par défaut
            return True

        # Tolérance large (50%) pour variations normales + marchés fermés
        ratio = median_close / api_price if api_price > 0 else 999
        if ratio < 0.5 or ratio > 2.0:
            logger.error(
                "❌ VALIDATION ÉCHOUÉE %s : bougies médiane=%.4f, prix API=%.4f, ratio=%.2f → REJETÉ",
                symbol, median_close, api_price, ratio
            )
            return False

        return True

    def get_candles(self, symbol: str = None, period: int = 5,
                    count: int = 100) -> list[dict]:
        """
        Retourne les bougies historiques + une bougie live en cours.
        La dernière bougie bouge en temps réel grâce au LivePriceTicker.
        """
        symbol = symbol or self.default_symbol
        cache_key = f"candles_{symbol}_{period}_{count}"
        cached = _cache_get(cache_key, CACHE_TTL_CANDLES)

        # Valider le cache existant (protection contre données corrompues)
        if cached and not self._validate_candles_vs_price(symbol, cached):
            logger.warning("⚠️  Cache invalide pour %s → purge et re-fetch", symbol)
            with _cache_lock:
                _cache.pop(cache_key, None)
            cached = None

        if not cached:
            candles = None
            # 1) Yahoo Finance
            candles = self._yahoo_candles(symbol, period, count)
            # Valider les bougies Yahoo
            if candles and not self._validate_candles_vs_price(symbol, candles):
                logger.error("❌ Yahoo bougies %s rejetées (prix incohérents)", symbol)
                candles = None
            # 2) CoinGecko fallback (crypto)
            if candles is None and symbol in COINGECKO_IDS:
                candles = self._coingecko_candles(symbol, period, count)
            # 3) Dernier recours : générer à partir du prix courant
            if candles is None:
                logger.warning("Pas de bougies pour %s – génération synthétique", symbol)
                candles = self._synthetic_candles(symbol, period, count)
            if candles:
                _cache_set(cache_key, candles)
            cached = candles or []

        # Synchroniser le LivePriceTicker avec le dernier close réel des bougies
        # pour éviter tout décalage entre le prix affiché et le graphique
        ticker = _get_ticker(symbol)
        if cached:
            last_candle_close = cached[-1]["close"]
            if last_candle_close > 0:
                ticker.set_base_price(last_candle_close)

        # Ajouter ou mettre à jour la bougie live (temps réel)
        live_candle = ticker.get_live_candle(period)
        if live_candle and cached:
            candles = list(cached)  # copie pour ne pas modifier le cache
            
            # Validation : vérifier que la bougie live est cohérente
            # avec les prix historiques (éviter les outliers)
            ref_price = candles[-1]["close"]
            live_close = live_candle["close"]
            if ref_price > 0 and abs(live_close - ref_price) / ref_price > 0.05:
                # Prix live trop éloigné (>5%), on ignore la bougie live
                return candles
            
            # Remplacer la dernière bougie si même période,
            # sinon ajouter en fin
            last_ctm = candles[-1]["ctm"] if candles else 0
            if live_candle["ctm"] == last_ctm:
                # Fusionner : garder l'open de l'historique, prendre
                # le close/high/low du live
                candles[-1] = {
                    "ctm": last_ctm,
                    "open": candles[-1]["open"],
                    "high": max(candles[-1]["high"], live_candle["high"]),
                    "low": min(candles[-1]["low"], live_candle["low"]),
                    "close": live_candle["close"],
                    "vol": candles[-1].get("vol", 0),
                }
            else:
                candles.append(live_candle)
                candles = candles[-(count):]
            return candles

        return list(cached)

    def _yahoo_candles(self, symbol: str, period: int, count: int) -> list[dict] | None:
        """Bougies via Yahoo Finance."""
        default_ticker = YAHOO_TICKERS.get(symbol)
        if not default_ticker:
            return None

        # Pour les futures, essayer le contrat actif (plus proche de XTB)
        ticker_name = _resolve_futures_ticker(symbol, default_ticker)

        yf_interval = YF_INTERVAL_MAP.get(period, "5m")
        need_aggregate = (period == 240)  # H4 = agrégation de bougies 1h

        # Calculer la période de téléchargement
        # Yahoo limite : 1m → 7 jours, 5m → 60 jours, 15m/30m/1h → 60 jours, 1d → max
        if period <= 1:
            yf_period = "5d"
        elif period <= 5:
            yf_period = "5d"
        elif period <= 60:
            yf_period = "60d"
        elif period <= 240:
            yf_period = "60d"   # télécharge en 1h, agrège en 4h
        else:
            yf_period = "1y"    # D1 → 1 an

        # Pour H4, demander plus de bougies 1h pour avoir assez après agrégation
        download_count = count * 4 + 10 if need_aggregate else count * 2

        try:
            df = yf.download(
                ticker_name, period=yf_period, interval=yf_interval,
                progress=False, auto_adjust=True
            )
            if df.empty:
                return None

            # Aplatir les colonnes MultiIndex (yfinance 0.2+)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [col[0] for col in df.columns]

            # Supprimer les lignes avec NaN
            df = df.dropna()

            candles = []
            for idx, row in df.iterrows():
                ts = int(idx.timestamp() * 1000) if hasattr(idx, 'timestamp') else int(time.time() * 1000)

                # Colonnes aplaties → accès direct
                o = float(row["Open"])
                h = float(row["High"])
                l = float(row["Low"])
                c = float(row["Close"])
                v = float(row["Volume"]) if "Volume" in row.index else 0

                candles.append({
                    "ctm": ts,
                    "open": round(o * PRICE_MULTIPLIER.get(symbol, 1), 6),
                    "high": round(h * PRICE_MULTIPLIER.get(symbol, 1), 6),
                    "low": round(l * PRICE_MULTIPLIER.get(symbol, 1), 6),
                    "close": round(c * PRICE_MULTIPLIER.get(symbol, 1), 6),
                    "vol": v,
                })

            # Agrégation H4 : regrouper les bougies 1h par blocs de 4
            if need_aggregate and candles:
                agg = []
                for i in range(0, len(candles), 4):
                    group = candles[i:i+4]
                    if not group:
                        break
                    agg.append({
                        "ctm": group[0]["ctm"],
                        "open": group[0]["open"],
                        "high": max(g["high"] for g in group),
                        "low": min(g["low"] for g in group),
                        "close": group[-1]["close"],
                        "vol": sum(g["vol"] for g in group),
                    })
                candles = agg

            # Prendre les N dernières bougies
            candles = candles[-count:]

            logger.info("Yahoo Finance : %d bougies %s pour %s (ticker=%s, close≈%.4f)",
                        len(candles), yf_interval, symbol, ticker_name,
                        candles[-1]["close"] if candles else 0)
            return candles if candles else None

        except Exception as e:
            logger.debug("Yahoo Finance bougies %s : %s", symbol, e)
            return None

    def invalidate_cache(self, symbol: str = None):
        """Purge le cache des bougies (un symbole ou tout)."""
        with _cache_lock:
            if symbol:
                keys_to_del = [k for k in _cache if k.startswith(f"candles_{symbol}_")]
                for k in keys_to_del:
                    del _cache[k]
                logger.info("Cache purgé pour %s (%d clés)", symbol, len(keys_to_del))
            else:
                keys_to_del = [k for k in _cache if k.startswith("candles_")]
                for k in keys_to_del:
                    del _cache[k]
                logger.info("Cache purgé entièrement (%d clés)", len(keys_to_del))

    def _coingecko_candles(self, symbol: str, period: int, count: int) -> list[dict] | None:
        """Bougies via CoinGecko (crypto)."""
        cg_id = COINGECKO_IDS.get(symbol)
        if not cg_id:
            return None

        # CoinGecko: days=1 → 5min, days=7-30 → hourly, days=90+ → daily
        # On demande 2 jours pour avoir assez de bougies 5min
        days = max(1, (count * period) // (24 * 60) + 1)
        days = min(days, 30)  # Limiter

        try:
            url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart?vs_currency=usd&days={days}"
            resp = requests.get(url, timeout=10)
            data = resp.json()

            prices = data.get("prices", [])
            if not prices:
                return None

            # Regrouper en bougies de N minutes
            candles = []
            bucket_ms = period * 60 * 1000
            current_bucket = prices[0][0] // bucket_ms * bucket_ms
            bucket_prices = []

            for ts_ms, price in prices:
                bucket = ts_ms // bucket_ms * bucket_ms
                if bucket != current_bucket:
                    if bucket_prices:
                        candles.append({
                            "ctm": current_bucket,
                            "open": round(bucket_prices[0], 2),
                            "high": round(max(bucket_prices), 2),
                            "low": round(min(bucket_prices), 2),
                            "close": round(bucket_prices[-1], 2),
                            "vol": 0,
                        })
                    current_bucket = bucket
                    bucket_prices = [price]
                else:
                    bucket_prices.append(price)

            # Dernière bougie
            if bucket_prices:
                candles.append({
                    "ctm": current_bucket,
                    "open": round(bucket_prices[0], 2),
                    "high": round(max(bucket_prices), 2),
                    "low": round(min(bucket_prices), 2),
                    "close": round(bucket_prices[-1], 2),
                    "vol": 0,
                })

            candles = candles[-count:]
            logger.info("CoinGecko : %d bougies pour %s", len(candles), symbol)
            return candles if candles else None

        except Exception as e:
            logger.debug("CoinGecko bougies %s : %s", symbol, e)
            return None

    def _synthetic_candles(self, symbol: str, period: int, count: int) -> list[dict]:
        """Génère des bougies synthétiques basées sur le prix courant réel."""
        price_info = self.get_current_price(symbol)
        mid = (price_info["bid"] + price_info["ask"]) / 2
        if mid == 0:
            mid = 1.0

        # Volatilité typique par actif
        vols = {
            "EURUSD": 0.0003, "GBPUSD": 0.0004, "USDJPY": 0.03,
            "GOLD": 0.8, "GASOLINE": 0.5, "BITCOIN": 50,
            "US500": 2.0, "DE40": 5.0,
        }
        vol = vols.get(symbol, mid * 0.0005)

        candles = []
        price = mid * (1 + np.random.normal(0, 0.005))  # léger décalage pour la première bougie
        now_ms = int(time.time() * 1000)

        for i in range(count):
            ts = now_ms - (count - i) * period * 60 * 1000
            o = price
            changes = np.random.normal(0, vol, 4)
            h = o + abs(changes[0])
            l = o - abs(changes[1])
            c = o + changes[2]
            price = c

            candles.append({
                "ctm": ts,
                "open": round(o, 6),
                "high": round(max(o, h, c), 6),
                "low": round(min(o, l, c), 6),
                "close": round(c, 6),
                "vol": 0,
            })

        return candles
