"""
============================================================
  webapp.py  –  Dashboard Web de Trading en temps réel
============================================================
Lance un serveur web local avec :
  • Recherche d'actifs (EURUSD, GOLD, BITCOIN, etc.)
  • Graphique candlestick en temps réel
  • Moyennes mobiles MA20 / MA50
  • Signaux BUY / SELL / HOLD
  • Tableau de bord avec indicateurs clés
  • Historique des signaux
  • Auto-refresh toutes les 2 secondes

Usage :
    python webapp.py
    → Ouvre http://localhost:5000 dans le navigateur
============================================================
"""

import json
import time
import threading
import logging
from datetime import datetime, timezone, timedelta
import zoneinfo

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

import config
from market_simulator import MarketSimulator
from real_data import RealDataProvider
from strategy import compute_moving_averages, detect_crossover, Signal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WEBAPP")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "tradeai-secret"
socketio = SocketIO(app, cors_allowed_origins="*")

# ── Fournisseurs de données par actif ─────────────────────────
# On crée un provider par actif pour garder l'historique en mémoire
_providers: dict[str, RealDataProvider | MarketSimulator] = {}
_signal_history: list[dict] = []
_use_real_data: bool = True   # True = données réelles, False = simulateur

# Actifs disponibles avec infos
AVAILABLE_ASSETS = {
    # ── Forex (13) ──
    "EURUSD":  {"name": "Euro / Dollar US",       "category": "Forex",   "emoji": "💶"},
    "GBPUSD":  {"name": "Livre / Dollar US",      "category": "Forex",   "emoji": "💷"},
    "USDJPY":  {"name": "Dollar US / Yen",        "category": "Forex",   "emoji": "💴"},
    "USDCHF":  {"name": "Dollar US / Franc Suisse","category": "Forex",  "emoji": "🇨🇭"},
    "AUDUSD":  {"name": "Dollar Australien / USD", "category": "Forex",  "emoji": "🇦🇺"},
    "USDCAD":  {"name": "Dollar US / Canadien",   "category": "Forex",   "emoji": "🇨🇦"},
    "NZDUSD":  {"name": "Dollar NZ / USD",        "category": "Forex",   "emoji": "🇳🇿"},
    "EURGBP":  {"name": "Euro / Livre",           "category": "Forex",   "emoji": "🇪🇺"},
    "EURJPY":  {"name": "Euro / Yen",             "category": "Forex",   "emoji": "🇪🇺"},
    "GBPJPY":  {"name": "Livre / Yen",            "category": "Forex",   "emoji": "💷"},
    "EURCHF":  {"name": "Euro / Franc Suisse",    "category": "Forex",   "emoji": "🇪🇺"},
    "AUDJPY":  {"name": "Dollar AUD / Yen",       "category": "Forex",   "emoji": "🇦🇺"},
    "CADJPY":  {"name": "Dollar CAD / Yen",       "category": "Forex",   "emoji": "🇨🇦"},
    # ── Indices (12) ──
    "US500":   {"name": "S&P 500",                 "category": "Indices", "emoji": "📈"},
    "US100":   {"name": "Nasdaq 100",              "category": "Indices", "emoji": "💻"},
    "US30":    {"name": "Dow Jones 30",            "category": "Indices", "emoji": "🏛️"},
    "DE40":    {"name": "DAX 40",                  "category": "Indices", "emoji": "🇩🇪"},
    "UK100":   {"name": "FTSE 100",               "category": "Indices", "emoji": "🇬🇧"},
    "FR40":    {"name": "CAC 40",                  "category": "Indices", "emoji": "🇫🇷"},
    "JP225":   {"name": "Nikkei 225",             "category": "Indices", "emoji": "🇯🇵"},
    "EU50":    {"name": "Euro Stoxx 50",           "category": "Indices", "emoji": "🇪🇺"},
    "AU200":   {"name": "ASX 200",                "category": "Indices", "emoji": "🇦🇺"},
    "HK50":    {"name": "Hang Seng",              "category": "Indices", "emoji": "🇭🇰"},
    "CN50":    {"name": "SSE Composite",           "category": "Indices", "emoji": "🇨🇳"},
    "VIX":     {"name": "Indice Volatilité",       "category": "Indices", "emoji": "⚡"},
    # ── Matières premières (14) ──
    "GOLD":    {"name": "Or (XAU/USD)",            "category": "Matières", "emoji": "🥇"},
    "SILVER":  {"name": "Argent (XAG/USD)",       "category": "Matières", "emoji": "🥈"},
    "GASOLINE": {"name": "Essence (RBOB)",        "category": "Matières", "emoji": "⛽"},
    "OIL":     {"name": "Pétrole WTI",            "category": "Matières", "emoji": "🛢️"},
    "BRENT":   {"name": "Pétrole Brent",          "category": "Matières", "emoji": "🛢️"},
    "NATGAS":  {"name": "Gaz Naturel",            "category": "Matières", "emoji": "🔥"},
    "COPPER":  {"name": "Cuivre",                 "category": "Matières", "emoji": "🔶"},
    "PLATINUM": {"name": "Platine",               "category": "Matières", "emoji": "⬜"},
    "PALLADIUM": {"name": "Palladium",            "category": "Matières", "emoji": "🔘"},
    "WHEAT":   {"name": "Blé",                    "category": "Matières", "emoji": "🌾"},
    "CORN":    {"name": "Maïs",                   "category": "Matières", "emoji": "🌽"},
    "SOYBEAN": {"name": "Soja",                   "category": "Matières", "emoji": "🫘"},
    "COTTON":  {"name": "Coton",                  "category": "Matières", "emoji": "🧶"},
    "COFFEE":  {"name": "Café",                   "category": "Matières", "emoji": "☕"},
    "SUGAR":   {"name": "Sucre",                  "category": "Matières", "emoji": "🍬"},
    "COCOA":   {"name": "Cacao",                  "category": "Matières", "emoji": "🍫"},
    # ── Crypto (12) ──
    "BITCOIN": {"name": "Bitcoin (BTC/USD)",       "category": "Crypto",  "emoji": "₿"},
    "ETHEREUM": {"name": "Ethereum (ETH/USD)",    "category": "Crypto",  "emoji": "⟠"},
    "SOLANA":  {"name": "Solana (SOL/USD)",       "category": "Crypto",  "emoji": "◎"},
    "XRP":     {"name": "Ripple (XRP/USD)",       "category": "Crypto",  "emoji": "✕"},
    "CARDANO": {"name": "Cardano (ADA/USD)",      "category": "Crypto",  "emoji": "🔵"},
    "DOGECOIN": {"name": "Dogecoin (DOGE/USD)",   "category": "Crypto",  "emoji": "🐕"},
    "POLKADOT": {"name": "Polkadot (DOT/USD)",    "category": "Crypto",  "emoji": "⬡"},
    "AVAX":    {"name": "Avalanche (AVAX/USD)",   "category": "Crypto",  "emoji": "🔺"},
    "CHAINLINK": {"name": "Chainlink (LINK/USD)", "category": "Crypto",  "emoji": "⬡"},
    "MATIC":   {"name": "Polygon (MATIC/USD)",    "category": "Crypto",  "emoji": "🟣"},
    "LITECOIN": {"name": "Litecoin (LTC/USD)",    "category": "Crypto",  "emoji": "Ł"},
    "BNB":     {"name": "BNB (BNB/USD)",          "category": "Crypto",  "emoji": "🟡"},
    # ── Actions US (11) ──
    "APPLE":   {"name": "Apple (AAPL)",            "category": "Actions", "emoji": "🍎"},
    "TESLA":   {"name": "Tesla (TSLA)",            "category": "Actions", "emoji": "🚗"},
    "NVIDIA":  {"name": "Nvidia (NVDA)",           "category": "Actions", "emoji": "🟩"},
    "MICROSOFT": {"name": "Microsoft (MSFT)",      "category": "Actions", "emoji": "🪟"},
    "AMAZON":  {"name": "Amazon (AMZN)",           "category": "Actions", "emoji": "📦"},
    "GOOGLE":  {"name": "Alphabet (GOOGL)",        "category": "Actions", "emoji": "🔍"},
    "META":    {"name": "Meta (META)",             "category": "Actions", "emoji": "👤"},
    "NETFLIX": {"name": "Netflix (NFLX)",          "category": "Actions", "emoji": "🎬"},
    "AMD":     {"name": "AMD (AMD)",               "category": "Actions", "emoji": "🔴"},
    "INTEL":   {"name": "Intel (INTC)",            "category": "Actions", "emoji": "🔷"},
    "COINBASE": {"name": "Coinbase (COIN)",        "category": "Actions", "emoji": "🪙"},
    # ── Actions EU (5) ──
    "LVMH":    {"name": "LVMH (MC.PA)",            "category": "Actions EU", "emoji": "👜"},
    "AIRBUS":  {"name": "Airbus (AIR.PA)",         "category": "Actions EU", "emoji": "✈️"},
    "SAP":     {"name": "SAP (SAP.DE)",            "category": "Actions EU", "emoji": "💼"},
    "SIEMENS": {"name": "Siemens (SIE.DE)",        "category": "Actions EU", "emoji": "⚙️"},
    "TOTALENERGIES": {"name": "TotalEnergies (TTE.PA)", "category": "Actions EU", "emoji": "🛢️"},
}


def get_provider(symbol: str):
    """Retourne (ou crée) le fournisseur de données pour un symbole."""
    if symbol not in _providers:
        if _use_real_data:
            provider = RealDataProvider(symbol=symbol)
            provider.connect()
            # Test rapide : essayer de récupérer un prix
            try:
                p = provider.get_current_price(symbol)
                if p["bid"] == 0 and p["ask"] == 0:
                    logger.warning("⚠️  %s → Prix réel indisponible pour le moment (bid/ask nuls)", symbol)
                else:
                    logger.info("✅ %s → Données RÉELLES", symbol)
            except Exception as e:
                # On garde quand même RealDataProvider pour réessayer aux appels suivants
                logger.warning("⚠️  %s → Erreur données réelles (on reste sur RealDataProvider) : %s", symbol, e)
            _providers[symbol] = provider
        else:
            sim = MarketSimulator(symbol=symbol)
            sim.connect()
            _providers[symbol] = sim
    return _providers[symbol]


# Nombre de bougies par timeframe (plus = plus de dézoom possible)
CANDLE_COUNT_BY_PERIOD = {
    1: 500,    # M1  → ~8h
    5: 500,    # M5  → ~42h ≈ 2j
    15: 400,   # M15 → ~100h ≈ 4j
    30: 350,   # M30 → ~175h ≈ 7j
    60: 500,   # H1  → ~500h ≈ 20j
    240: 300,  # H4  → ~1200h ≈ 50j
    1440: 365, # D1  → 1 an
}

def analyze_asset(symbol: str, period: int = None) -> dict:
    """
    Analyse complète d'un actif : prix, bougies, MA, signal.
    Retourne un dictionnaire avec toutes les données pour le dashboard.
    """
    if period is None:
        period = config.CANDLE_PERIOD
    candle_count = CANDLE_COUNT_BY_PERIOD.get(period, 100)
    provider = get_provider(symbol)

    # Prix actuel (flux live)
    price_info = provider.get_current_price(symbol)
    bid = price_info["bid"]
    ask = price_info["ask"]
    spread = price_info["spread"]
    mid = round((bid + ask) / 2, 6)

    # Bougies historiques + éventuelle bougie live
    candles = provider.get_candles(symbol, period, count=candle_count)

    # Pour l'analyse technique, on ne garde que les bougies CLÔTURÉES
    if candles and candles[-1].get("live"):
        candles_for_analysis = candles[:-1]
    else:
        candles_for_analysis = candles

    # Moyennes mobiles et indicateurs calculés uniquement sur les bougies clôturées
    closes = [c["close"] for c in candles_for_analysis]
    ma_fast, ma_slow = compute_moving_averages(closes)

    # Signal
    signal = detect_crossover(ma_fast, ma_slow)

    # Dernières valeurs MA
    ma_fast_val = round(float(ma_fast.iloc[-1]), 6) if not ma_fast.iloc[-1] != ma_fast.iloc[-1] else None
    ma_slow_val = round(float(ma_slow.iloc[-1]), 6) if not ma_slow.iloc[-1] != ma_slow.iloc[-1] else None

    # Variation (dernier close clôturé vs open de la première bougie = variation session)
    if len(candles_for_analysis) >= 2:
        first_open = candles_for_analysis[0]["open"]
        curr_close = candles_for_analysis[-1]["close"]
        change = curr_close - first_open
        change_pct = (change / first_open * 100) if first_open != 0 else 0
    else:
        change = 0
        change_pct = 0

    # High / Low du jour (sur les dernières bougies clôturées)
    day_high = max(c["high"] for c in candles_for_analysis) if candles_for_analysis else 0
    day_low = min(c["low"] for c in candles_for_analysis) if candles_for_analysis else 0

    # RSI simple (14 périodes)
    rsi = _compute_rsi(closes, 14)

    # Volatilité (écart-type des rendements)
    if len(closes) > 2:
        returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
        volatility = round((sum(r**2 for r in returns) / len(returns)) ** 0.5 * 100, 4)
    else:
        volatility = 0

    # Enregistrer le signal dans l'historique
    if signal != Signal.HOLD:
        _signal_history.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "symbol": symbol,
            "signal": signal.value,
            "price": mid,
        })
        # Garder max 50 signaux
        if len(_signal_history) > 50:
            _signal_history.pop(0)

    # Préparer les données des bougies pour Chart.js
    candle_data = []
    ma_fast_data = []
    ma_slow_data = []
    labels = []

    for i, c in enumerate(candles):
        # Timestamp Unix en secondes (pour TradingView chart)
        ts_sec = int(c["ctm"] / 1000)
        t = datetime.fromtimestamp(ts_sec).strftime("%H:%M")
        labels.append(t)
        candle_data.append({
            "x": t,
            "o": c["open"],
            "h": c["high"],
            "l": c["low"],
            "c": c["close"],
            "ts": ts_sec,
        })
        if i < len(ma_fast) and not (ma_fast.iloc[i] != ma_fast.iloc[i]):
            ma_fast_data.append({"x": t, "y": round(float(ma_fast.iloc[i]), 6), "ts": ts_sec})
        if i < len(ma_slow) and not (ma_slow.iloc[i] != ma_slow.iloc[i]):
            ma_slow_data.append({"x": t, "y": round(float(ma_slow.iloc[i]), 6), "ts": ts_sec})

    # Source des données
    is_real = isinstance(provider, RealDataProvider)
    asset_info = AVAILABLE_ASSETS.get(symbol, {"name": symbol, "category": "Autre", "emoji": "📊"})

    # Statut du marché (horaires France / Europe/Paris)
    market_status = _get_market_status(symbol, asset_info["category"])

    return {
        "symbol": symbol,
        "name": asset_info["name"],
        "category": asset_info["category"],
        "emoji": asset_info["emoji"],
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread": spread,
        "change": round(change, 6),
        "change_pct": round(change_pct, 4),
        "day_high": day_high,
        "day_low": day_low,
        "ma_fast": ma_fast_val,
        "ma_slow": ma_slow_val,
        "ma_fast_period": config.MA_FAST,
        "ma_slow_period": config.MA_SLOW,
        "signal": signal.value,
        "rsi": rsi,
        "volatility": volatility,
        "candles": candle_data,
        "ma_fast_data": ma_fast_data,
        "ma_slow_data": ma_slow_data,
        "labels": labels,
        "signal_history": _signal_history[-20:],
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "source": "live" if is_real else "simulation",
        "market_status": market_status,
        "period": period,
    }


# ── Horaires de marché (heure de Paris) ──────────────────────

def _get_paris_now():
    """Retourne l'heure actuelle à Paris (Europe/Paris)."""
    try:
        paris_tz = zoneinfo.ZoneInfo("Europe/Paris")
    except Exception:
        paris_tz = timezone(timedelta(hours=1))
    return datetime.now(paris_tz)


def _get_market_status(symbol: str, category: str) -> dict:
    """
    Retourne le statut du marché pour un actif donné.
    Horaires en heure de Paris (CET/CEST).
    """
    now = _get_paris_now()
    weekday = now.weekday()  # 0=lundi, 6=dimanche
    hour = now.hour
    minute = now.minute
    hm = hour * 60 + minute

    # Crypto : 24/7
    if category == "Crypto":
        return {"open": True, "label": "Ouvert 24/7", "color": "green",
                "next_event": "Marché crypto toujours ouvert"}

    # Weekend : tout fermé sauf crypto
    if weekday >= 5:
        return {"open": False, "label": "Fermé (week-end)", "color": "red",
                "next_event": "Réouverture lundi"}

    # Forex : quasi 24h en semaine
    if category == "Forex":
        if weekday <= 3:
            return {"open": True, "label": "Ouvert", "color": "green",
                    "next_event": "Forex ouvert 24h en semaine"}
        if weekday == 4:
            if hm < 23 * 60:
                return {"open": True, "label": "Ouvert", "color": "green",
                        "next_event": "Fermeture vendredi 23h"}
            else:
                return {"open": False, "label": "Fermé", "color": "red",
                        "next_event": "Réouverture dimanche 23h"}

    # Actions US : 15h30-22h (heure Paris)
    if category == "Actions":
        open_hm = 15 * 60 + 30
        close_hm = 22 * 60
        if open_hm <= hm < close_hm:
            remaining = close_hm - hm
            h_r, m_r = divmod(remaining, 60)
            return {"open": True, "label": "Ouvert (US)", "color": "green",
                    "next_event": f"Fermeture dans {h_r}h{m_r:02d}"}
        elif 10 * 60 <= hm < open_hm:
            return {"open": False, "label": "Pré-marché", "color": "yellow",
                    "next_event": "Ouverture US à 15h30"}
        elif close_hm <= hm < close_hm + 120:
            return {"open": False, "label": "Après-marché", "color": "yellow",
                    "next_event": "Fermé — réouverture demain 15h30"}
        else:
            return {"open": False, "label": "Fermé", "color": "red",
                    "next_event": "Ouverture US à 15h30"}

    # Actions EU : 9h-17h30 (heure Paris)
    if category == "Actions EU":
        open_hm = 9 * 60
        close_hm = 17 * 60 + 30
        if open_hm <= hm < close_hm:
            remaining = close_hm - hm
            h_r, m_r = divmod(remaining, 60)
            return {"open": True, "label": "Ouvert (EU)", "color": "green",
                    "next_event": f"Fermeture dans {h_r}h{m_r:02d}"}
        elif 8 * 60 <= hm < open_hm:
            return {"open": False, "label": "Pré-marché", "color": "yellow",
                    "next_event": "Ouverture EU à 9h00"}
        else:
            return {"open": False, "label": "Fermé", "color": "red",
                    "next_event": "Ouverture EU à 9h00"}

    # Indices
    if category == "Indices":
        if symbol in ("US500", "US100", "US30", "VIX"):
            if 0 * 60 <= hm < 23 * 60:
                return {"open": True, "label": "Ouvert (Futures)", "color": "green",
                        "next_event": "Session US principale 15h30-22h"}
            else:
                return {"open": False, "label": "Maintenance", "color": "yellow",
                        "next_event": "Réouverture dans 1h"}
        elif symbol in ("DE40", "FR40", "EU50", "UK100"):
            if 8 * 60 <= hm < 22 * 60:
                return {"open": True, "label": "Ouvert", "color": "green",
                        "next_event": "Fermeture à 22h"}
            else:
                return {"open": False, "label": "Fermé", "color": "red",
                        "next_event": "Ouverture à 8h"}
        elif symbol == "JP225":
            if (1 * 60 <= hm < 7 * 60 + 30) or (8 * 60 + 30 <= hm < 15 * 60 + 15):
                return {"open": True, "label": "Ouvert (Tokyo)", "color": "green",
                        "next_event": "Session japonaise"}
            else:
                return {"open": False, "label": "Fermé", "color": "red",
                        "next_event": "Session Tokyo 1h-7h30 (Paris)"}
        elif symbol in ("HK50", "CN50"):
            if (2 * 60 + 30 <= hm < 9 * 60) or (10 * 60 <= hm < 17 * 60):
                return {"open": True, "label": "Ouvert (Asie)", "color": "green",
                        "next_event": "Session asiatique"}
            else:
                return {"open": False, "label": "Fermé", "color": "red",
                        "next_event": "Session suivante"}
        else:
            if 1 * 60 <= hm < 8 * 60:
                return {"open": True, "label": "Ouvert", "color": "green",
                        "next_event": "Session Océanie/Asie"}
            else:
                return {"open": False, "label": "Fermé", "color": "red",
                        "next_event": "Prochaine session"}

    # Matières premières : quasi 24h
    if category == "Matières":
        if 1 * 60 <= hm < 23 * 60:
            return {"open": True, "label": "Ouvert", "color": "green",
                    "next_event": "Marchés commodités ouverts"}
        else:
            return {"open": False, "label": "Maintenance", "color": "yellow",
                    "next_event": "Réouverture à 1h"}

    return {"open": True, "label": "—", "color": "gray", "next_event": ""}


def _compute_rsi(closes: list[float], period: int = 14) -> float:
    """Calcule le RSI (Relative Strength Index)."""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    recent = deltas[-period:]
    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


# ── Routes Flask ──────────────────────────────────────────────

@app.route("/")
def index():
    """Page principale du dashboard."""
    resp = app.make_response(render_template("index.html", assets=AVAILABLE_ASSETS))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


@app.route("/api/assets")
def api_assets():
    """Liste des actifs disponibles."""
    return jsonify(AVAILABLE_ASSETS)


@app.route("/api/analyze/<symbol>")
def api_analyze(symbol: str):
    """Analyse complète d'un actif. Accepte ?period=1|5|15|30|60|240|1440"""
    symbol = symbol.upper()
    if symbol not in AVAILABLE_ASSETS:
        return jsonify({"error": f"Actif '{symbol}' non disponible"}), 404
    # Timeframe optionnel (défaut = config.CANDLE_PERIOD)
    period = request.args.get("period", type=int)
    valid_periods = [1, 5, 15, 30, 60, 240, 1440]
    if period and period not in valid_periods:
        period = config.CANDLE_PERIOD
    data = analyze_asset(symbol, period)
    return jsonify(data)


@app.route("/api/search")
def api_search():
    """Recherche d'actifs par nom ou symbole."""
    q = request.args.get("q", "").upper().strip()
    results = {}
    for sym, info in AVAILABLE_ASSETS.items():
        if q in sym or q in info["name"].upper() or q in info["category"].upper():
            results[sym] = info
    return jsonify(results)


@app.route("/api/signals")
def api_signals():
    """Historique des signaux."""
    return jsonify(_signal_history[-30:])


@app.route("/api/clear_cache")
def api_clear_cache():
    """Purge le cache des bougies (utile si données corrompues)."""
    sym = request.args.get("symbol", "").upper().strip()
    try:
        from real_data import _cache, _cache_lock
        with _cache_lock:
            if sym:
                keys = [k for k in _cache if k.startswith(f"candles_{sym}_")]
                for k in keys:
                    del _cache[k]
                return jsonify({"cleared": len(keys), "symbol": sym})
            else:
                keys = [k for k in _cache if k.startswith("candles_")]
                for k in keys:
                    del _cache[k]
                return jsonify({"cleared": len(keys), "symbol": "ALL"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/scan_all")
def api_scan_all():
    """
    Scan tous les actifs : analyse rapide + deep analysis.
    Retourne une liste triée par score de confluence décroissant.
    """
    results = []
    for sym, info in AVAILABLE_ASSETS.items():
        try:
            # Quick price data
            provider = get_provider(sym)
            price_info = provider.get_current_price(sym)
            bid = price_info["bid"]
            ask = price_info["ask"]
            mid = round((bid + ask) / 2, 6)

            candles = provider.get_candles(sym, config.CANDLE_PERIOD, count=100)
            closes = [c["close"] for c in candles]
            highs  = [c["high"]  for c in candles]
            lows   = [c["low"]   for c in candles]

            if len(candles) < 30:
                continue

            # RSI
            rsi = _compute_rsi(closes, 14)

            # Change %
            if len(closes) >= 2 and closes[-2] != 0:
                change = closes[-1] - closes[-2]
                change_pct = (change / closes[-2]) * 100
            else:
                change = 0
                change_pct = 0

            # Run deep analysis via the existing endpoint logic
            # We call it internally to avoid HTTP overhead
            deep_resp = _run_deep_analysis_internal(sym)

            entry = {
                "symbol": sym,
                "name": info["name"],
                "category": info["category"],
                "emoji": info["emoji"],
                "price": mid,
                "bid": bid,
                "ask": ask,
                "change_pct": round(change_pct, 2),
                "rsi": rsi,
                "signal": deep_resp.get("verdict", "HOLD").upper(),
                "verdict_text": deep_resp.get("verdict_text", "—"),
                "verdict_emoji": deep_resp.get("verdict_emoji", "⏸"),
                "golden_rule": deep_resp.get("golden_rule", ""),
                "confluence_score": deep_resp.get("confluence_score", 0),
                "criteria_summary": [],
                "price_targets": deep_resp.get("price_targets"),
            }

            # Extract summary from criteria
            for c in deep_resp.get("criteria", []):
                entry["criteria_summary"].append({
                    "id": c["id"],
                    "name": c["name"],
                    "icon": c["icon"],
                    "direction": c["direction"],
                })

            results.append(entry)
        except Exception as e:
            logger.warning("Scan %s failed: %s", sym, e)
            results.append({
                "symbol": sym,
                "name": info["name"],
                "category": info["category"],
                "emoji": info["emoji"],
                "price": 0,
                "change_pct": 0,
                "rsi": 50,
                "signal": "HOLD",
                "verdict_text": "Erreur",
                "verdict_emoji": "⚠️",
                "golden_rule": "",
                "confluence_score": 0,
                "criteria_summary": [],
                "price_targets": None,
            })

    # Sort by confluence score descending
    results.sort(key=lambda x: x.get("confluence_score", 0), reverse=True)
    return jsonify(results)


def _run_deep_analysis_internal(symbol: str) -> dict:
    """
    Logique interne d'analyse institutionnelle — retourne un dict (pas jsonify).
    Utilisé par l'API endpoint ET par /api/scan_all.
    """
    symbol = symbol.upper()
    if symbol not in AVAILABLE_ASSETS:
        return {"error": f"Actif '{symbol}' non disponible"}

    provider = get_provider(symbol)
    candles = provider.get_candles(symbol, config.CANDLE_PERIOD, count=100)

    # Ne garder que les bougies clôturées pour l'analyse institutionnelle
    if candles and candles[-1].get("live"):
        candles = candles[:-1]

    closes = [c["close"] for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    opens  = [c["open"]  for c in candles]
    n = len(candles)

    if n < 30:
        return {"error": "Pas assez de données (min 30 bougies)"}

    ma_fast, ma_slow = compute_moving_averages(closes)
    rsi = _compute_rsi(closes, 14)
    mid = closes[-1]

    # Signal de croisement MA basé uniquement sur les bougies clôturées
    from strategy import detect_crossover, Signal as StrategySignal
    ma_cross_signal = detect_crossover(ma_fast, ma_slow)

    # ─── Outils d'analyse ──────────────────────────────────
    def ema(data, period):
        k = 2 / (period + 1)
        vals = [data[0]]
        for i in range(1, len(data)):
            vals.append(data[i] * k + vals[-1] * (1 - k))
        return vals

    # ATR
    atr_len = min(14, n - 1)
    trs = []
    for i in range(n - atr_len, n):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    atr = sum(trs) / len(trs) if trs else 1

    # MACD
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    macd_line = [ema12[i] - ema26[i] for i in range(n)]
    macd_signal_line = ema(macd_line, 9)
    macd_hist = [macd_line[i] - macd_signal_line[i] for i in range(n)]

    # Pivots locaux (swing highs / swing lows)
    def find_pivots(data_h, data_l, left=5, right=3):
        swing_highs, swing_lows = [], []
        for i in range(left, len(data_h) - right):
            if all(data_h[i] >= data_h[j] for j in range(i - left, i + right + 1) if j != i):
                swing_highs.append((i, data_h[i]))
            if all(data_l[i] <= data_l[j] for j in range(i - left, i + right + 1) if j != i):
                swing_lows.append((i, data_l[i]))
        return swing_highs, swing_lows

    swing_highs, swing_lows = find_pivots(highs, lows, left=5, right=3)

    # MA values
    ma20_val = float(ma_fast.iloc[-1]) if not (ma_fast.iloc[-1] != ma_fast.iloc[-1]) else None
    ma50_val = float(ma_slow.iloc[-1]) if not (ma_slow.iloc[-1] != ma_slow.iloc[-1]) else None

    # Support / Résistance de base (pour price targets)
    supports_list = sorted([p[1] for p in swing_lows if p[1] < mid], reverse=True)
    resistances_list = sorted([p[1] for p in swing_highs if p[1] > mid])
    support = supports_list[0] if supports_list else min(lows[-30:])
    resistance = resistances_list[0] if resistances_list else max(highs[-30:])
    support2 = supports_list[1] if len(supports_list) > 1 else support - atr
    resistance2 = resistances_list[1] if len(resistances_list) > 1 else resistance + atr

    results = []
    bullish_count = 0
    bearish_count = 0
    # Scores internes pour la confluence (critère #6)
    _scores = {}

    # ═══════════════════════════════════════════════════════
    # #1  STRUCTURE DU MARCHÉ  (HH/HL vs LH/LL)
    # ═══════════════════════════════════════════════════════
    # Analyser les séquences de swing highs et swing lows
    hh_count, lh_count = 0, 0
    if len(swing_highs) >= 2:
        for i in range(1, len(swing_highs)):
            if swing_highs[i][1] > swing_highs[i - 1][1]:
                hh_count += 1   # Higher High
            elif swing_highs[i][1] < swing_highs[i - 1][1]:
                lh_count += 1   # Lower High

    hl_count, ll_count = 0, 0
    if len(swing_lows) >= 2:
        for i in range(1, len(swing_lows)):
            if swing_lows[i][1] > swing_lows[i - 1][1]:
                hl_count += 1   # Higher Low
            elif swing_lows[i][1] < swing_lows[i - 1][1]:
                ll_count += 1   # Lower Low

    # Tendance récente (pivots de la 2e moitié seulement)
    recent_sh = [s for s in swing_highs if s[0] >= n // 2]
    recent_sl = [s for s in swing_lows if s[0] >= n // 2]
    recent_hh = sum(1 for i in range(1, len(recent_sh)) if recent_sh[i][1] > recent_sh[i - 1][1])
    recent_lh = sum(1 for i in range(1, len(recent_sh)) if recent_sh[i][1] < recent_sh[i - 1][1])
    recent_hl = sum(1 for i in range(1, len(recent_sl)) if recent_sl[i][1] > recent_sl[i - 1][1])
    recent_ll = sum(1 for i in range(1, len(recent_sl)) if recent_sl[i][1] < recent_sl[i - 1][1])

    # Score de structure
    struct_bull = hh_count + hl_count + (recent_hh + recent_hl) * 2  # pivots plus récents = plus de poids
    struct_bear = lh_count + ll_count + (recent_lh + recent_ll) * 2

    # Prix par rapport aux MA pour confirmer
    above_ma50 = ma50_val and mid > ma50_val
    below_ma50 = ma50_val and mid < ma50_val

    if struct_bull > struct_bear + 1 and (above_ma50 or not ma50_val):
        struct_dir = "bullish"
        struct_text = (f"Structure HAUSSIÈRE : {hh_count} Higher Highs, {hl_count} Higher Lows. "
                       f"Récent : {recent_hh} HH, {recent_hl} HL. "
                       f"L'IA privilégie les ACHATS dans cette tendance.")
        bullish_count += 1
        _scores["structure"] = 1
    elif struct_bear > struct_bull + 1 and (below_ma50 or not ma50_val):
        struct_dir = "bearish"
        struct_text = (f"Structure BAISSIÈRE : {lh_count} Lower Highs, {ll_count} Lower Lows. "
                       f"Récent : {recent_lh} LH, {recent_ll} LL. "
                       f"L'IA privilégie les VENTES dans cette tendance.")
        bearish_count += 1
        _scores["structure"] = -1
    elif struct_bull > struct_bear:
        struct_dir = "bullish"
        struct_text = (f"Légère structure haussière ({hh_count} HH + {hl_count} HL vs {lh_count} LH + {ll_count} LL). "
                       f"Tendance faible, prudence.")
        bullish_count += 1
        _scores["structure"] = 0.5
    elif struct_bear > struct_bull:
        struct_dir = "bearish"
        struct_text = (f"Légère structure baissière ({lh_count} LH + {ll_count} LL vs {hh_count} HH + {hl_count} HL). "
                       f"Tendance faible, prudence.")
        bearish_count += 1
        _scores["structure"] = -0.5
    else:
        struct_dir = "neutral"
        struct_text = (f"Marché en RANGE : sommets et creux proches "
                       f"({hh_count} HH, {lh_count} LH, {hl_count} HL, {ll_count} LL). Pas de tendance dominante.")
        _scores["structure"] = 0

    results.append({
        "id": 1, "name": "Structure du marché",
        "icon": "🏗️", "direction": struct_dir, "detail": struct_text,
    })

    # ═══════════════════════════════════════════════════════
    # #2  ZONES DE LIQUIDITÉ
    # ═══════════════════════════════════════════════════════
    # Chercher les zones où plusieurs sommets/creux sont alignés (clusters)
    # → Ce sont des zones d'accumulation de stop-loss
    tolerance = atr * 0.5  # les niveaux à ±0.5 ATR sont considérés comme un cluster

    def find_clusters(levels, tol):
        """Regroupe les niveaux proches en clusters avec leur poids."""
        if not levels:
            return []
        sorted_levels = sorted(levels)
        clusters = []
        current = [sorted_levels[0]]
        for i in range(1, len(sorted_levels)):
            if sorted_levels[i] - current[-1] <= tol:
                current.append(sorted_levels[i])
            else:
                avg = sum(current) / len(current)
                clusters.append({"level": avg, "count": len(current), "values": current})
                current = [sorted_levels[i]]
        avg = sum(current) / len(current)
        clusters.append({"level": avg, "count": len(current), "values": current})
        return sorted(clusters, key=lambda x: x["count"], reverse=True)

    # Clusters de sommets (résistances / liquidité vendeuse)
    all_highs_levels = [p[1] for p in swing_highs]
    high_clusters = find_clusters(all_highs_levels, tolerance)
    strong_res = [c for c in high_clusters if c["count"] >= 2]

    # Clusters de creux (supports / liquidité acheteuse)
    all_lows_levels = [p[1] for p in swing_lows]
    low_clusters = find_clusters(all_lows_levels, tolerance)
    strong_sup = [c for c in low_clusters if c["count"] >= 2]

    # Niveaux psychologiques (nombre rond)
    def find_psych_levels(price, atr_val):
        """Trouve les niveaux ronds proches du prix."""
        # Adapter la granularité au prix
        if price > 10000:
            step = 100
        elif price > 1000:
            step = 50
        elif price > 100:
            step = 10
        elif price > 10:
            step = 1
        elif price > 1:
            step = 0.1
        else:
            step = 0.01
        base = round(price / step) * step
        levels = []
        for mult in range(-3, 4):
            lv = base + mult * step
            dist = abs(lv - price)
            if dist < atr_val * 5:
                levels.append({"level": round(lv, 8), "distance": dist, "distance_atr": round(dist / atr_val, 1)})
        return sorted(levels, key=lambda x: x["distance"])

    psych = find_psych_levels(mid, atr)

    # Déterminer si le prix approche une zone de liquidité
    liq_above = []
    liq_below = []
    for c in strong_res:
        if c["level"] > mid and (c["level"] - mid) < atr * 3:
            liq_above.append(c)
    for c in strong_sup:
        if c["level"] < mid and (mid - c["level"]) < atr * 3:
            liq_below.append(c)

    # Le prix vient-il de chasser la liquidité ? (touché un cluster récemment)
    liq_swept_above = any((max(highs[-3:]) >= c["level"]) and (closes[-1] < c["level"]) for c in strong_res if c["level"] > mid - atr)
    liq_swept_below = any((min(lows[-3:]) <= c["level"]) and (closes[-1] > c["level"]) for c in strong_sup if c["level"] < mid + atr)

    psych_near = [p for p in psych if p["distance_atr"] < 1.5]
    psych_text = ", ".join([f"{p['level']:.5g} ({p['distance_atr']} ATR)" for p in psych_near[:3]])

    if liq_swept_above:
        liq_dir = "bearish"
        liq_text = (f"CHASSE DE LIQUIDITÉ au-dessus ! Le prix a touché les stops vendeurs "
                    f"({strong_res[0]['count']}x sommets à ~{strong_res[0]['level']:.5g}) puis est redescendu. "
                    f"Signal de retournement baissier.")
        bearish_count += 1
        _scores["liquidity"] = -1
    elif liq_swept_below:
        liq_dir = "bullish"
        liq_text = (f"CHASSE DE LIQUIDITÉ en-dessous ! Le prix a touché les stops acheteurs "
                    f"({strong_sup[0]['count']}x creux à ~{strong_sup[0]['level']:.5g}) puis est remonté. "
                    f"Signal de retournement haussier.")
        bullish_count += 1
        _scores["liquidity"] = 1
    elif liq_above and not liq_below:
        liq_dir = "bearish"
        liq_text = (f"Zone de liquidité vendeuse au-dessus à ~{liq_above[0]['level']:.5g} "
                    f"({liq_above[0]['count']}x sommets alignés). "
                    f"Le prix pourrait aller chercher ces stops avant de redescendre. Niveaux psycho: {psych_text}")
        _scores["liquidity"] = -0.5
    elif liq_below and not liq_above:
        liq_dir = "bullish"
        liq_text = (f"Zone de liquidité acheteuse en-dessous à ~{liq_below[0]['level']:.5g} "
                    f"({liq_below[0]['count']}x creux alignés). "
                    f"Le prix pourrait aller chercher ces stops avant de remonter. Niveaux psycho: {psych_text}")
        _scores["liquidity"] = 0.5
    else:
        liq_dir = "neutral"
        n_res = len(strong_res)
        n_sup = len(strong_sup)
        liq_text = (f"{n_res} zones de liquidité au-dessus, {n_sup} en-dessous. "
                    f"Pas de chasse récente détectée. Niveaux psycho proches: {psych_text if psych_text else 'aucun'}")
        _scores["liquidity"] = 0

    results.append({
        "id": 2, "name": "Zones de liquidité",
        "icon": "💧", "direction": liq_dir, "detail": liq_text,
    })

    # ═══════════════════════════════════════════════════════
    # #3  FAUX BREAKOUT (Fake Breakout Detection)
    # ═══════════════════════════════════════════════════════
    # Vérifier si dans les 5 dernières bougies le prix a cassé un S/R
    # puis est revenu à l'intérieur → piège / faux signal
    fake_bull = False   # faux breakout baissier → signal haussier
    fake_bear = False   # faux breakout haussier → signal baissier
    fake_details = []

    for i in range(-5, 0):
        idx = n + i
        if idx < 1:
            continue
        h_i, l_i, c_i = highs[idx], lows[idx], closes[idx]

        # Faux breakout de résistance
        # Le prix est monté au-dessus de la résistance MAIS a clôturé en-dessous
        if resistance and h_i > resistance and c_i < resistance:
            fake_bear = True
            fake_details.append(f"Bougie {i}: mèche au-dessus de R ({resistance:.5g}) mais clôture en-dessous")

        # Même chose avec les clusters de résistance
        for cr in strong_res:
            if h_i > cr["level"] and c_i < cr["level"] and (cr["level"] - mid) < atr * 2:
                fake_bear = True
                fake_details.append(f"Bougie {i}: rejet du cluster de {cr['count']} sommets à {cr['level']:.5g}")

        # Faux breakout de support
        if support and l_i < support and c_i > support:
            fake_bull = True
            fake_details.append(f"Bougie {i}: mèche sous S ({support:.5g}) mais clôture au-dessus")

        for cs in strong_sup:
            if l_i < cs["level"] and c_i > cs["level"] and (mid - cs["level"]) < atr * 2:
                fake_bull = True
                fake_details.append(f"Bougie {i}: rejet du cluster de {cs['count']} creux à {cs['level']:.5g}")

    # Confirmation : la bougie actuelle va dans la direction opposée au breakout
    current_bullish = closes[-1] > opens[-1]
    current_bearish = closes[-1] < opens[-1]

    if fake_bull and current_bullish:
        fb_dir = "bullish"
        fb_text = (f"FAUX BREAKOUT BAISSIER détecté ! {fake_details[0]}. "
                   f"Le prix est revenu au-dessus → piège vendeur, hausse probable.")
        bullish_count += 1
        _scores["fakeout"] = 1
    elif fake_bear and current_bearish:
        fb_dir = "bearish"
        fb_text = (f"FAUX BREAKOUT HAUSSIER détecté ! {fake_details[0]}. "
                   f"Le prix est revenu en-dessous → piège acheteur, baisse probable.")
        bearish_count += 1
        _scores["fakeout"] = -1
    elif fake_bull:
        fb_dir = "bullish"
        fb_text = (f"Tentative de faux breakout baissier : {fake_details[0]}. "
                   f"Attente de confirmation (bougie haussière).")
        _scores["fakeout"] = 0.5
    elif fake_bear:
        fb_dir = "bearish"
        fb_text = (f"Tentative de faux breakout haussier : {fake_details[0]}. "
                   f"Attente de confirmation (bougie baissière).")
        _scores["fakeout"] = -0.5
    else:
        fb_dir = "neutral"
        fb_text = "Aucun faux breakout détecté sur les 5 dernières bougies. Les cassures récentes sont cohérentes."
        _scores["fakeout"] = 0

    results.append({
        "id": 3, "name": "Faux Breakout",
        "icon": "🪤", "direction": fb_dir, "detail": fb_text,
    })

    # ═══════════════════════════════════════════════════════
    # #4  ZONES INSTITUTIONNELLES (Order Blocks)
    # ═══════════════════════════════════════════════════════
    # Un order block = dernière bougie opposée avant une impulsion forte
    # Bullish OB : dernière bougie rouge avant un fort mouvement haussier
    # Bearish OB : dernière bougie verte avant un fort mouvement baissier
    ob_bull = []
    ob_bear = []

    for i in range(1, n - 2):
        body = abs(closes[i + 1] - opens[i + 1])
        avg_body = sum(abs(closes[j] - opens[j]) for j in range(max(0, i - 10), i)) / max(1, min(10, i))

        # Impulsion : bougie suivante a un corps > 2× la moyenne
        is_impulse = body > avg_body * 2 and body > atr * 0.5

        if is_impulse:
            # Bullish OB : bougie i est rouge, bougie i+1 est verte forte
            if closes[i] < opens[i] and closes[i + 1] > opens[i + 1]:
                ob_bull.append({
                    "index": i,
                    "zone_high": opens[i],
                    "zone_low": lows[i],
                    "strength": body / avg_body if avg_body > 0 else 1,
                })
            # Bearish OB : bougie i est verte, bougie i+1 est rouge forte
            elif closes[i] > opens[i] and closes[i + 1] < opens[i + 1]:
                ob_bear.append({
                    "index": i,
                    "zone_high": highs[i],
                    "zone_low": opens[i],
                    "strength": body / avg_body if avg_body > 0 else 1,
                })

    # OB le plus récent et non encore atteint
    active_bull_ob = [ob for ob in ob_bull if mid >= ob["zone_low"] - atr * 0.3 and mid <= ob["zone_high"] + atr * 0.3]
    active_bear_ob = [ob for ob in ob_bear if mid >= ob["zone_low"] - atr * 0.3 and mid <= ob["zone_high"] + atr * 0.3]
    # OB proches (en approche)
    nearby_bull_ob = [ob for ob in ob_bull if ob["zone_low"] < mid and (mid - ob["zone_low"]) < atr * 3 and ob not in active_bull_ob]
    nearby_bear_ob = [ob for ob in ob_bear if ob["zone_high"] > mid and (ob["zone_high"] - mid) < atr * 3 and ob not in active_bear_ob]

    if active_bull_ob:
        best_ob = max(active_bull_ob, key=lambda x: x["strength"])
        ob_dir = "bullish"
        ob_text = (f"Prix SUR un Order Block haussier (bougie {best_ob['index']}, force {best_ob['strength']:.1f}x). "
                   f"Zone : {best_ob['zone_low']:.5g} - {best_ob['zone_high']:.5g}. "
                   f"Les institutions ont probablement des ordres d'achat ici → rebond haussier probable.")
        bullish_count += 1
        _scores["institutional"] = 1
    elif active_bear_ob:
        best_ob = max(active_bear_ob, key=lambda x: x["strength"])
        ob_dir = "bearish"
        ob_text = (f"Prix SUR un Order Block baissier (bougie {best_ob['index']}, force {best_ob['strength']:.1f}x). "
                   f"Zone : {best_ob['zone_low']:.5g} - {best_ob['zone_high']:.5g}. "
                   f"Les institutions ont probablement des ordres de vente ici → rejet baissier probable.")
        bearish_count += 1
        _scores["institutional"] = -1
    elif nearby_bull_ob:
        best_ob = max(nearby_bull_ob, key=lambda x: x["strength"])
        ob_dir = "bullish"
        ob_text = (f"Order Block haussier proche en-dessous (force {best_ob['strength']:.1f}x). "
                   f"Zone : {best_ob['zone_low']:.5g} - {best_ob['zone_high']:.5g}. "
                   f"Attendre un pullback vers cette zone pour un meilleur point d'entrée.")
        _scores["institutional"] = 0.5
    elif nearby_bear_ob:
        best_ob = max(nearby_bear_ob, key=lambda x: x["strength"])
        ob_dir = "bearish"
        ob_text = (f"Order Block baissier proche au-dessus (force {best_ob['strength']:.1f}x). "
                   f"Zone : {best_ob['zone_low']:.5g} - {best_ob['zone_high']:.5g}. "
                   f"Attendre un pullback vers cette zone pour une meilleure vente.")
        _scores["institutional"] = -0.5
    else:
        ob_dir = "neutral"
        ob_text = (f"Aucun Order Block actif à proximité. "
                   f"{len(ob_bull)} OB haussiers et {len(ob_bear)} OB baissiers détectés sur l'historique.")
        _scores["institutional"] = 0

    results.append({
        "id": 4, "name": "Zones institutionnelles",
        "icon": "🏦", "direction": ob_dir, "detail": ob_text,
    })

    # ═══════════════════════════════════════════════════════
    # #5  MOMENTUM (taille des bougies, accélération, mèches)
    # ═══════════════════════════════════════════════════════
    # Analyser les 15 dernières bougies
    mom_window = min(15, n)
    bodies = []
    wicks_ratio = []
    directions = []
    for i in range(n - mom_window, n):
        body = closes[i] - opens[i]
        abs_body = abs(body)
        candle_range = highs[i] - lows[i] if highs[i] != lows[i] else 0.0001
        wick = candle_range - abs_body
        bodies.append(body)
        wicks_ratio.append(wick / candle_range)
        directions.append(1 if body > 0 else (-1 if body < 0 else 0))

    # Momentum en accélération ? Comparer taille des 5 dernières vs 5 précédentes
    recent_abs = [abs(b) for b in bodies[-5:]]
    older_abs = [abs(b) for b in bodies[-10:-5]] if len(bodies) >= 10 else [abs(b) for b in bodies[:5]]
    avg_recent = sum(recent_abs) / len(recent_abs) if recent_abs else 0
    avg_older = sum(older_abs) / len(older_abs) if older_abs else 0.0001
    acceleration = avg_recent / avg_older if avg_older > 0 else 1

    # Direction dominante des 5 dernières
    recent_dir_sum = sum(directions[-5:])
    # Mèches importantes (indécision / rejet) dans les 3 dernières
    high_wick_recent = sum(1 for w in wicks_ratio[-3:] if w > 0.6)

    # MACD momentum confirmé
    macd_confirming_bull = macd_hist[-1] > 0 and macd_hist[-1] > macd_hist[-2]
    macd_confirming_bear = macd_hist[-1] < 0 and macd_hist[-1] < macd_hist[-2]

    # RSI momentum
    rsi_strong_bull = rsi > 55
    rsi_strong_bear = rsi < 45

    if recent_dir_sum >= 3 and acceleration > 1.3 and high_wick_recent <= 1:
        mom_dir = "bullish"
        mom_text = (f"Momentum HAUSSIER FORT : {sum(1 for d in directions[-5:] if d > 0)}/5 bougies vertes, "
                    f"accélération x{acceleration:.1f}, bougies longues. "
                    f"{'MACD confirme.' if macd_confirming_bull else 'MACD ne confirme pas encore.'}")
        bullish_count += 1
        _scores["momentum"] = 1
    elif recent_dir_sum <= -3 and acceleration > 1.3 and high_wick_recent <= 1:
        mom_dir = "bearish"
        mom_text = (f"Momentum BAISSIER FORT : {sum(1 for d in directions[-5:] if d < 0)}/5 bougies rouges, "
                    f"accélération x{acceleration:.1f}, bougies longues. "
                    f"{'MACD confirme.' if macd_confirming_bear else 'MACD ne confirme pas encore.'}")
        bearish_count += 1
        _scores["momentum"] = -1
    elif high_wick_recent >= 2:
        # Beaucoup de mèches = indécision / ralentissement
        if recent_dir_sum > 0:
            mom_dir = "neutral"
            mom_text = (f"RALENTISSEMENT haussier : mouvement montant mais {high_wick_recent}/3 bougies avec mèches importantes. "
                        f"Perte de vitesse, les vendeurs résistent. Accélération: x{acceleration:.1f}")
        elif recent_dir_sum < 0:
            mom_dir = "neutral"
            mom_text = (f"RALENTISSEMENT baissier : mouvement descendant mais {high_wick_recent}/3 bougies avec mèches importantes. "
                        f"Perte de vitesse, les acheteurs résistent. Accélération: x{acceleration:.1f}")
        else:
            mom_dir = "neutral"
            mom_text = f"INDÉCISION : mèches importantes sur les bougies récentes (+{high_wick_recent}/3). Le marché hésite."
        _scores["momentum"] = 0
    elif recent_dir_sum >= 2 and (macd_confirming_bull or rsi_strong_bull):
        mom_dir = "bullish"
        mom_text = (f"Momentum haussier modéré ({sum(1 for d in directions[-5:] if d > 0)}/5 vertes). "
                    f"Accélération: x{acceleration:.1f}. RSI: {rsi}. "
                    f"{'MACD positif.' if macd_confirming_bull else ''}")
        bullish_count += 1
        _scores["momentum"] = 0.5
    elif recent_dir_sum <= -2 and (macd_confirming_bear or rsi_strong_bear):
        mom_dir = "bearish"
        mom_text = (f"Momentum baissier modéré ({sum(1 for d in directions[-5:] if d < 0)}/5 rouges). "
                    f"Accélération: x{acceleration:.1f}. RSI: {rsi}. "
                    f"{'MACD négatif.' if macd_confirming_bear else ''}")
        bearish_count += 1
        _scores["momentum"] = -0.5
    else:
        mom_dir = "neutral"
        mom_text = (f"Pas de momentum clair. Bougies mixtes, accélération x{acceleration:.1f}. "
                    f"RSI: {rsi}. MACD histogramme: {macd_hist[-1]:.5g}")
        _scores["momentum"] = 0

    results.append({
        "id": 5, "name": "Momentum",
        "icon": "🚀", "direction": mom_dir, "detail": mom_text,
    })

    # ═══════════════════════════════════════════════════════
    # #6  CONFLUENCE DES SIGNAUX
    # ═══════════════════════════════════════════════════════
    # Compter les éléments alignés :
    # - Structure du marché
    # - Zone de liquidité
    # - Faux breakout
    # - Zone institutionnelle
    # - Momentum
    # + éléments supplémentaires : MA position, RSI, S/R

    # Éléments bonus (non comptés dans les 5 premiers critères)
    _scores["ma_position"] = 0
    if ma50_val:
        if mid > ma50_val and ma20_val and ma20_val > ma50_val:
            _scores["ma_position"] = 1
        elif mid < ma50_val and ma20_val and ma20_val < ma50_val:
            _scores["ma_position"] = -1
        elif mid > ma50_val:
            _scores["ma_position"] = 0.5
        elif mid < ma50_val:
            _scores["ma_position"] = -0.5

    _scores["rsi"] = 0
    if rsi < 30:
        _scores["rsi"] = 1
    elif rsi > 70:
        _scores["rsi"] = -1
    elif rsi < 45:
        _scores["rsi"] = 0.5
    elif rsi > 55:
        _scores["rsi"] = -0.5

    # S/R : le prix est-il sur une zone clé ?
    price_range_val = resistance - support if resistance != support else atr
    price_pos = (mid - support) / price_range_val if price_range_val != 0 else 0.5
    _scores["sr_position"] = 0
    if price_pos < 0.25:
        _scores["sr_position"] = 0.5  # près du support = favorable achat
    elif price_pos > 0.75:
        _scores["sr_position"] = -0.5  # près de la résistance = favorable vente

    # Alignement avec le signal de croisement de moyennes mobiles
    _scores["ma_crossover"] = 0
    if ma_cross_signal == StrategySignal.BUY:
        _scores["ma_crossover"] = 1
    elif ma_cross_signal == StrategySignal.SELL:
        _scores["ma_crossover"] = -1

    # Calcul de la confluence totale
    total_score = sum(_scores.values())
    aligned_bull = sum(1 for v in _scores.values() if v > 0)
    aligned_bear = sum(1 for v in _scores.values() if v < 0)
    all_factors = len(_scores)

    # Texte de détail
    factor_details = []
    factor_names = {
        "structure": "Structure", "liquidity": "Liquidité", "fakeout": "Faux Breakout",
        "institutional": "Institutionnel", "momentum": "Momentum",
        "ma_position": "Moyennes Mobiles", "rsi": "RSI", "sr_position": "Position S/R",
        "ma_crossover": "Croisement MA",
    }
    for k, v in _scores.items():
        if v > 0:
            factor_details.append(f"{factor_names.get(k, k)}")
        elif v < 0:
            factor_details.append(f"{factor_names.get(k, k)}")

    bull_factors = [factor_names.get(k, k) for k, v in _scores.items() if v > 0]
    bear_factors = [factor_names.get(k, k) for k, v in _scores.items() if v < 0]

    if total_score >= 3 and aligned_bull >= 4:
        conf_dir = "bullish"
        conf_text = (f"FORTE CONFLUENCE HAUSSIÈRE : {aligned_bull}/{all_factors} facteurs alignés. "
                     f"Score: {total_score:+.1f}. "
                     f"Haussiers: {', '.join(bull_factors)}. "
                     f"Trade LONG recommandé avec conviction élevée.")
        bullish_count += 1
    elif total_score <= -3 and aligned_bear >= 4:
        conf_dir = "bearish"
        conf_text = (f"FORTE CONFLUENCE BAISSIÈRE : {aligned_bear}/{all_factors} facteurs alignés. "
                     f"Score: {total_score:+.1f}. "
                     f"Baissiers: {', '.join(bear_factors)}. "
                     f"Trade SHORT recommandé avec conviction élevée.")
        bearish_count += 1
    elif total_score >= 1.5 and aligned_bull >= 3:
        conf_dir = "bullish"
        conf_text = (f"Confluence haussière modérée : {aligned_bull}/{all_factors} facteurs haussiers. "
                     f"Score: {total_score:+.1f}. "
                     f"Haussiers: {', '.join(bull_factors)}. Baissiers: {', '.join(bear_factors) if bear_factors else 'aucun'}.")
        bullish_count += 1
    elif total_score <= -1.5 and aligned_bear >= 3:
        conf_dir = "bearish"
        conf_text = (f"Confluence baissière modérée : {aligned_bear}/{all_factors} facteurs baissiers. "
                     f"Score: {total_score:+.1f}. "
                     f"Baissiers: {', '.join(bear_factors)}. Haussiers: {', '.join(bull_factors) if bull_factors else 'aucun'}.")
        bearish_count += 1
    else:
        conf_dir = "neutral"
        conf_text = (f"PAS DE CONFLUENCE : {aligned_bull} facteurs haussiers, {aligned_bear} baissiers sur {all_factors}. "
                     f"Score: {total_score:+.1f}. "
                     f"Signaux contradictoires → NE PAS TRADER. "
                     f"Attendre un alignement de 3-4+ facteurs.")

    results.append({
        "id": 6, "name": "Confluence",
        "icon": "🎯", "direction": conf_dir, "detail": conf_text,
    })

    # ═══════════════════════════════════════════════════════
    # VERDICT FINAL
    # ═══════════════════════════════════════════════════════
    total_criteria = len(results)
    # On ne valide un trade que si AU MOINS 4 critères clairs sont alignés
    # (pour augmenter la précision et filtrer les signaux moyens)
    if bullish_count >= 5:
        verdict = "BUY"
        verdict_text = f"🟢 {bullish_count}/{total_criteria} critères HAUSSIERS → SIGNAL D'ACHAT TRÈS FORT"
        verdict_emoji = "🚀"
        confidence = round(bullish_count / total_criteria * 100)
    elif bullish_count >= 4:
        verdict = "BUY"
        verdict_text = f"🟢 {bullish_count}/{total_criteria} critères HAUSSIERS → SIGNAL D'ACHAT FORT"
        verdict_emoji = "🚀"
        confidence = round(bullish_count / total_criteria * 100)
    # Moins de 4 critères haussiers → pas de trade pour plus de précision
    elif bearish_count >= 5:
        verdict = "SELL"
        verdict_text = f"🔴 {bearish_count}/{total_criteria} critères BAISSIERS → SIGNAL DE VENTE TRÈS FORT"
        verdict_emoji = "📉"
        confidence = round(bearish_count / total_criteria * 100)
    elif bearish_count >= 4:
        verdict = "SELL"
        verdict_text = f"🔴 {bearish_count}/{total_criteria} critères BAISSIERS → SIGNAL DE VENTE FORT"
        verdict_emoji = "📉"
        confidence = round(bearish_count / total_criteria * 100)
    else:
        verdict = "HOLD"
        verdict_text = (f"🟡 Pas de confluence suffisante "
                        f"({bullish_count} haussiers, {bearish_count} baissiers) → ATTENDRE")
        verdict_emoji = "⏸️"
        confidence = 0

    # ═══════════════════════════════════════════════════════
    # OBJECTIFS DE PRIX
    # ═══════════════════════════════════════════════════════
    entry = mid
    price_targets = {}

    if verdict == "BUY":
        sl = min(support - atr * 0.3, mid - atr * 1.5)
        # Si un order block haussier est actif, placer le SL sous la zone OB
        if active_bull_ob:
            ob_sl = active_bull_ob[0]["zone_low"] - atr * 0.2
            sl = min(sl, ob_sl)
        risk = entry - sl
        if risk <= 0:
            risk = atr
            sl = entry - risk

        tp1 = entry + risk * 1.0
        tp2 = entry + risk * 2.0
        tp3 = entry + risk * 3.0

        if resistance > entry and tp1 > resistance:
            tp1 = resistance
        if resistance2 > entry and tp2 > resistance2:
            tp2 = resistance2

        rr_ratio = round((tp3 - entry) / risk, 1) if risk > 0 else 0
        quality = "Excellent" if rr_ratio >= 3 else ("Bon" if rr_ratio >= 2 else "Correct")
        price_targets = {
            "direction": "BUY",
            "direction_text": "📗 ACHAT (Long)",
            "entry": round(entry, 6),
            "stop_loss": round(sl, 6),
            "tp1": round(tp1, 6), "tp2": round(tp2, 6), "tp3": round(tp3, 6),
            "risk_pips": round(risk, 6),
            "risk_pct": round((risk / entry) * 100, 2),
            "rr1_pct": round(((tp1 - entry) / entry) * 100, 2),
            "rr2_pct": round(((tp2 - entry) / entry) * 100, 2),
            "rr3_pct": round(((tp3 - entry) / entry) * 100, 2),
            "support": round(support, 6), "resistance": round(resistance, 6),
            "atr": round(atr, 6),
            "rr_ratio": rr_ratio,
            "quality": quality,
            "potential_gain": round(((tp3 - entry) / entry) * 100, 2),
            "potential_loss": round(((entry - sl) / entry) * 100, 2),
            "scenario": (
                f"Le prix est à {entry:.5g}. Structure haussière détectée avec "
                f"{bullish_count} critère(s) aligné(s). "
                f"Zone de profit potentiel entre {tp1:.5g} (+{((tp1-entry)/entry*100):.1f}%) "
                f"et {tp3:.5g} (+{((tp3-entry)/entry*100):.1f}%). "
                f"Risque limité à {sl:.5g} (-{((entry-sl)/entry*100):.1f}%). "
                f"Ratio Risk/Reward de 1:{rr_ratio}. Trade {quality}."
            ),
            "conseil": (f"Entrée à {entry:.5g}. SL sous support/OB ({sl:.5g}). "
                        f"TP1 ratio 1:1 → {tp1:.5g}. Sécuriser 50% au TP1."),
        }

    elif verdict == "SELL":
        sl = max(resistance + atr * 0.3, mid + atr * 1.5)
        if active_bear_ob:
            ob_sl = active_bear_ob[0]["zone_high"] + atr * 0.2
            sl = max(sl, ob_sl)
        risk = sl - entry
        if risk <= 0:
            risk = atr
            sl = entry + risk

        tp1 = entry - risk * 1.0
        tp2 = entry - risk * 2.0
        tp3 = entry - risk * 3.0

        if support < entry and tp1 < support:
            tp1 = support
        if support2 < entry and tp2 < support2:
            tp2 = support2

        rr_ratio = round((entry - tp3) / risk, 1) if risk > 0 else 0
        quality = "Excellent" if rr_ratio >= 3 else ("Bon" if rr_ratio >= 2 else "Correct")
        price_targets = {
            "direction": "SELL",
            "direction_text": "📕 VENTE (Short)",
            "entry": round(entry, 6),
            "stop_loss": round(sl, 6),
            "tp1": round(tp1, 6), "tp2": round(tp2, 6), "tp3": round(tp3, 6),
            "risk_pips": round(risk, 6),
            "risk_pct": round((risk / entry) * 100, 2),
            "rr1_pct": round(((entry - tp1) / entry) * 100, 2),
            "rr2_pct": round(((entry - tp2) / entry) * 100, 2),
            "rr3_pct": round(((entry - tp3) / entry) * 100, 2),
            "support": round(support, 6), "resistance": round(resistance, 6),
            "atr": round(atr, 6),
            "rr_ratio": rr_ratio,
            "quality": quality,
            "potential_gain": round(((entry - tp3) / entry) * 100, 2),
            "potential_loss": round(((sl - entry) / entry) * 100, 2),
            "scenario": (
                f"Le prix est à {entry:.5g}. Structure baissière détectée avec "
                f"{bearish_count} critère(s) aligné(s). "
                f"Zone de profit potentiel entre {tp1:.5g} (-{((entry-tp1)/entry*100):.1f}%) "
                f"et {tp3:.5g} (-{((entry-tp3)/entry*100):.1f}%). "
                f"Risque limité à {sl:.5g} (+{((sl-entry)/entry*100):.1f}%). "
                f"Ratio Risk/Reward de 1:{rr_ratio}. Trade {quality}."
            ),
            "conseil": (f"Entrée à {entry:.5g}. SL au-dessus résistance/OB ({sl:.5g}). "
                        f"TP1 ratio 1:1 → {tp1:.5g}. Sécuriser 50% au TP1."),
        }

    else:
        risk_est = atr * 1.5
        price_targets = {
            "direction": "HOLD",
            "direction_text": "⏸️ PAS DE TRADE",
            "entry": round(entry, 6),
            "stop_loss": None, "tp1": None, "tp2": None, "tp3": None,
            "risk_pips": round(risk_est, 6),
            "risk_pct": round((risk_est / entry) * 100, 2),
            "rr1_pct": None, "rr2_pct": None, "rr3_pct": None,
            "support": round(support, 6), "resistance": round(resistance, 6),
            "atr": round(atr, 6),
            "rr_ratio": 0,
            "quality": "Pas de trade",
            "potential_gain": None,
            "potential_loss": None,
            "scenario": (
                f"Le prix est à {entry:.5g}. Pas de confluence suffisante "
                f"({bullish_count} haussier(s) vs {bearish_count} baissier(s)). "
                f"Support à {support:.5g}, résistance à {resistance:.5g}. "
                f"Attendre un signal clair avant de trader."
            ),
            "conseil": "Pas de confluence. Attendre 3+ critères alignés.",
        }

    # Résumé
    ma20_str = f"{ma20_val:.5g}" if ma20_val else "N/A"
    ma50_str = f"{ma50_val:.5g}" if ma50_val else "N/A"
    context_summary = (
        f"Analysé {n} bougies • ATR: {atr:.5g} • "
        f"MA20: {ma20_str} • MA50: {ma50_str} • "
        f"MACD: {macd_hist[-1]:.5g} • RSI: {rsi} • "
        f"Pivots: {len(swing_highs)} swing highs, {len(swing_lows)} swing lows • "
        f"OB: {len(ob_bull)} haussiers, {len(ob_bear)} baissiers • "
        f"Score confluence: {total_score:+.1f}"
    )

    return {
        "symbol": symbol,
        "price": mid,
        "criteria": results,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "neutral_count": total_criteria - bullish_count - bearish_count,
        "verdict": verdict,
        "verdict_text": verdict_text,
        "verdict_emoji": verdict_emoji,
        "confidence": confidence,
        "golden_rule": (f"Confluence : {max(bullish_count, bearish_count)}/6 critères alignés"
                        + (" → JE TRADE ✅" if max(bullish_count, bearish_count) >= 3 else " → J'ATTENDS ⏳")),
        "price_targets": price_targets,
        "context": context_summary,
        "confluence_score": total_score,
        "scores_detail": _scores,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }


@app.route("/api/deep_analysis/<symbol>")
def api_deep_analysis(symbol: str):
    """
    Analyse institutionnelle avancée — 6 critères.
    Wrapper HTTP autour de _run_deep_analysis_internal.
    """
    result = _run_deep_analysis_internal(symbol)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


# ── WebSocket pour temps réel ─────────────────────────────────

@socketio.on("subscribe")
def handle_subscribe(data):
    """Un client s'abonne aux mises à jour d'un actif."""
    symbol = data.get("symbol", "EURUSD").upper()
    logger.info("Client abonné à %s", symbol)
    # Envoyer immédiatement les données
    analysis = analyze_asset(symbol)
    emit("update", analysis)


@socketio.on("request_update")
def handle_request_update(data):
    """Le client demande une mise à jour."""
    symbol = data.get("symbol", "EURUSD").upper()
    analysis = analyze_asset(symbol)
    emit("update", analysis)


# ── Point d'entrée ────────────────────────────────────────────

if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    print()
    print("=" * 55)
    print("  TradeAI Dashboard")
    print("  Donnees : REELLES (Yahoo + CoinGecko + ExchangeRate)")
    print("  Ouvrez :  http://localhost:5000")
    print("=" * 55)
    print()
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
