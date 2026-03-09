"""
============================================================
  main.py  –  Boucle principale du robot de trading XTB
============================================================
Usage :
    python main.py              → lance le robot (mode configuré dans .env)
    python main.py --paper      → force le mode paper trading
    python main.py --live       → force le mode live (ordres réels)
    python main.py --offline    → mode 100% offline (données simulées)
============================================================
"""

import sys
import time
import logging
from datetime import datetime

import config
from xtb_api import XTBClient
from market_simulator import MarketSimulator
from strategy import analyze, Signal

# ── Configuration du logging ──────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-10s] %(levelname)-7s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("tradeai.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("MAIN")


# ── Paper Trading (simulation) ────────────────────────────────

class PaperTrader:
    """
    Simule l'exécution d'ordres sans envoyer de requêtes réelles.
    Tient un journal des trades virtuels.
    """

    def __init__(self):
        self.trades: list[dict] = []
        self.current_position: dict | None = None
        self._order_counter = 1000

    def open_trade(self, symbol: str, cmd: int, volume: float, price: float, sl: float, tp: float) -> dict:
        side = "BUY" if cmd == 0 else "SELL"
        order_id = self._order_counter
        self._order_counter += 1
        trade = {
            "order": order_id,
            "symbol": symbol,
            "cmd": cmd,
            "side": side,
            "volume": volume,
            "open_price": price,
            "sl": sl,
            "tp": tp,
            "open_time": datetime.now().isoformat(),
        }
        self.current_position = trade
        self.trades.append(trade)
        logger.info(
            "📝 [PAPER] Ordre %s ouvert : %s %.2f lots @ %.5f  SL=%.5f  TP=%.5f",
            side, symbol, volume, price, sl, tp,
        )
        return {"order": order_id}

    def close_position(self, price: float):
        if self.current_position:
            pos = self.current_position
            side = pos["side"]
            pnl = (price - pos["open_price"]) if pos["cmd"] == 0 else (pos["open_price"] - price)
            pnl *= pos["volume"] * 100_000  # approximation PnL en devise de base
            logger.info(
                "📝 [PAPER] Position fermée @ %.5f  PnL estimé : %.2f",
                price, pnl,
            )
            self.current_position = None

    @property
    def has_position(self) -> bool:
        return self.current_position is not None


# ── Fonctions utilitaires ─────────────────────────────────────

def calculate_sl_tp(price: float, cmd: int, pip_value: float) -> tuple[float, float]:
    """
    Calcule le Stop Loss et le Take Profit à partir du prix d'entrée.
    cmd : 0 = BUY, 1 = SELL
    """
    sl_distance = config.STOP_LOSS_PIPS * pip_value
    tp_distance = config.TAKE_PROFIT_PIPS * pip_value

    if cmd == 0:  # BUY
        sl = round(price - sl_distance, 5)
        tp = round(price + tp_distance, 5)
    else:         # SELL
        sl = round(price + sl_distance, 5)
        tp = round(price - tp_distance, 5)

    return sl, tp


def get_pip_value(symbol_info: dict) -> float:
    """
    Retourne la valeur d'un pip pour le symbole.
    Exemple : EURUSD → 0.0001
    """
    precision = symbol_info.get("pip", 4)
    return 10 ** (-precision)


# ── Boucle principale ────────────────────────────────────────

def run():
    """Lance la boucle principale du robot."""

    offline_mode = "--offline" in sys.argv
    paper_mode = config.PAPER_TRADING or offline_mode
    # Surcharge via argument de ligne de commande
    if "--paper" in sys.argv:
        paper_mode = True
    elif "--live" in sys.argv:
        paper_mode = False
        offline_mode = False

    if offline_mode:
        mode_label = "OFFLINE (données simulées, aucune connexion)"
    elif paper_mode:
        mode_label = "PAPER TRADING (simulation)"
    else:
        mode_label = "LIVE TRADING (ordres réels)"

    logger.info("=" * 60)
    logger.info("  🤖  TradeAI  –  Robot de Trading XTB")
    logger.info("  Mode    : %s", mode_label)
    logger.info("  Actif   : %s", config.SYMBOL)
    logger.info("  MA      : %d / %d", config.MA_FAST, config.MA_SLOW)
    logger.info("  Volume  : %.2f lots", config.VOLUME)
    logger.info("  SL/TP   : %d / %d pips", config.STOP_LOSS_PIPS, config.TAKE_PROFIT_PIPS)
    logger.info("  Période : %d min (bougies)", config.CANDLE_PERIOD)
    logger.info("  Boucle  : toutes les %d secondes", config.LOOP_INTERVAL)
    logger.info("=" * 60)

    # Connexion (API réelle ou simulateur offline)
    if offline_mode:
        client = MarketSimulator(symbol=config.SYMBOL)
    else:
        client = XTBClient()

    if not client.connect():
        logger.critical("Impossible de se connecter. Arrêt du robot.")
        return

    paper = PaperTrader() if paper_mode else None

    try:
        iteration = 0
        while True:
            iteration += 1
            logger.info("─── Itération #%d (%s) ───", iteration, datetime.now().strftime("%H:%M:%S"))

            # 1. Récupérer le prix actuel
            price_info = client.get_current_price(config.SYMBOL)
            bid = price_info["bid"]
            ask = price_info["ask"]
            spread = price_info["spread"]
            pip_val = get_pip_value(price_info)

            if bid == 0.0:
                logger.warning("Prix indisponible, on réessaie…")
                time.sleep(config.LOOP_INTERVAL)
                continue

            logger.info("💰 Prix %s  bid=%.5f  ask=%.5f  spread=%.5f", config.SYMBOL, bid, ask, spread)

            # 2. Récupérer les bougies
            candles = client.get_candles(config.SYMBOL, config.CANDLE_PERIOD)
            if not candles:
                logger.warning("Aucune bougie reçue, on réessaie…")
                time.sleep(config.LOOP_INTERVAL)
                continue

            logger.info("📊 %d bougies récupérées (dernière clôture : %.5f)", len(candles), candles[-1]["close"])

            # 3. Analyser le marché
            signal = analyze(candles)

            # 4. Exécuter le signal
            if signal == Signal.BUY:
                entry_price = ask  # On achète au prix ask
                sl, tp = calculate_sl_tp(entry_price, cmd=0, pip_value=pip_val)

                if paper_mode:
                    # Fermer position opposée éventuelle
                    if paper.has_position and paper.current_position["cmd"] == 1:
                        paper.close_position(ask)
                    if not paper.has_position:
                        paper.open_trade(config.SYMBOL, 0, config.VOLUME, entry_price, sl, tp)
                else:
                    # Fermer les positions SELL existantes
                    _close_opposite_positions(client, symbol=config.SYMBOL, opposite_cmd=1)
                    # Vérifier qu'on n'a pas déjà un BUY ouvert
                    if not _has_position(client, config.SYMBOL, cmd=0):
                        result = client.open_trade(
                            symbol=config.SYMBOL,
                            cmd=0,
                            volume=config.VOLUME,
                            price=entry_price,
                            sl=sl,
                            tp=tp,
                        )
                        logger.info("📤 Ordre BUY envoyé : %s", result)

            elif signal == Signal.SELL:
                entry_price = bid  # On vend au prix bid
                sl, tp = calculate_sl_tp(entry_price, cmd=1, pip_value=pip_val)

                if paper_mode:
                    if paper.has_position and paper.current_position["cmd"] == 0:
                        paper.close_position(bid)
                    if not paper.has_position:
                        paper.open_trade(config.SYMBOL, 1, config.VOLUME, entry_price, sl, tp)
                else:
                    _close_opposite_positions(client, symbol=config.SYMBOL, opposite_cmd=0)
                    if not _has_position(client, config.SYMBOL, cmd=1):
                        result = client.open_trade(
                            symbol=config.SYMBOL,
                            cmd=1,
                            volume=config.VOLUME,
                            price=entry_price,
                            sl=sl,
                            tp=tp,
                        )
                        logger.info("📤 Ordre SELL envoyé : %s", result)

            else:
                logger.info("⏸️  Pas de signal, on attend…")

            # 5. Ping pour maintenir la connexion
            client.ping()

            # 6. Attendre avant la prochaine itération
            logger.info("⏳ Prochaine analyse dans %d secondes…\n", config.LOOP_INTERVAL)
            time.sleep(config.LOOP_INTERVAL)

    except KeyboardInterrupt:
        logger.info("🛑 Arrêt demandé par l'utilisateur (Ctrl+C).")
    except Exception as exc:
        logger.exception("Erreur inattendue : %s", exc)
    finally:
        client.disconnect()
        if paper_mode and paper:
            logger.info("── Résumé Paper Trading ──")
            for t in paper.trades:
                logger.info("  %s %s %.2f lots @ %.5f", t["side"], t["symbol"], t["volume"], t["open_price"])
            logger.info("Total ordres simulés : %d", len(paper.trades))
        logger.info("Robot arrêté.")


# ── Helpers pour la gestion des positions (mode live) ─────────

def _has_position(client: XTBClient, symbol: str, cmd: int) -> bool:
    """Vérifie si une position ouverte existe pour le symbole et la direction donnés."""
    trades = client.get_open_trades()
    return any(t["symbol"] == symbol and t["cmd"] == cmd for t in trades)


def _close_opposite_positions(client: XTBClient, symbol: str, opposite_cmd: int):
    """Ferme toutes les positions ouvertes dans la direction opposée."""
    trades = client.get_open_trades()
    for t in trades:
        if t["symbol"] == symbol and t["cmd"] == opposite_cmd:
            close_price = t.get("close_price", t.get("open_price", 0))
            client.close_trade(
                order_id=t["order2"],
                symbol=symbol,
                cmd=opposite_cmd,
                volume=t["volume"],
                price=close_price,
            )
            logger.info("🔄 Position opposée fermée (order=%s)", t["order2"])


# ── Point d'entrée ────────────────────────────────────────────

if __name__ == "__main__":
    run()
