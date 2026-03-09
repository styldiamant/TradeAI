"""
============================================================
  backtest.py  –  Backtester simple pour la stratégie MA
============================================================
Usage :
    python backtest.py                   → backtest sur EURUSD (défaut)
    python backtest.py --symbol GASOLINE → backtest sur GASOLINE
    python backtest.py --period 15       → bougies de 15 min
    python backtest.py --candles 500     → 500 bougies historiques
    python backtest.py --offline         → données simulées (sans API)

Le backtester :
  1. Se connecte à XTB et télécharge les bougies historiques
  2. Simule la stratégie bougie par bougie
  3. Affiche un récapitulatif des trades et des performances
============================================================
"""

import sys
import argparse
import logging
from datetime import datetime

import pandas as pd

import config
from xtb_api import XTBClient
from market_simulator import MarketSimulator
from strategy import compute_moving_averages, Signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-10s] %(levelname)-7s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("BACKTEST")


class BacktestTrade:
    """Représente un trade simulé pendant le backtest."""

    def __init__(self, side: str, entry_price: float, entry_index: int, sl: float, tp: float):
        self.side = side
        self.entry_price = entry_price
        self.entry_index = entry_index
        self.sl = sl
        self.tp = tp
        self.exit_price: float = 0.0
        self.exit_index: int = 0
        self.pnl: float = 0.0
        self.exit_reason: str = ""

    def close(self, exit_price: float, exit_index: int, reason: str = "signal"):
        self.exit_price = exit_price
        self.exit_index = exit_index
        self.exit_reason = reason
        if self.side == "BUY":
            self.pnl = (self.exit_price - self.entry_price)
        else:
            self.pnl = (self.entry_price - self.exit_price)

    def __repr__(self):
        return (
            f"{self.side} @ {self.entry_price:.5f} → {self.exit_price:.5f} "
            f"| PnL = {self.pnl:+.5f} ({self.exit_reason})"
        )


def run_backtest(candles: list[dict], ma_fast: int, ma_slow: int,
                 sl_pips: int, tp_pips: int) -> list[BacktestTrade]:
    """
    Exécute le backtest sur les bougies fournies.
    Retourne la liste des trades simulés.
    """
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    ma_f, ma_s = compute_moving_averages(closes)

    # Déterminer la valeur d'un pip (heuristique basée sur le prix)
    avg_price = sum(closes) / len(closes)
    if avg_price > 50:
        pip_value = 0.01       # Indices, commodités
    elif avg_price > 10:
        pip_value = 0.01
    else:
        pip_value = 0.0001     # Forex

    trades: list[BacktestTrade] = []
    current_trade: BacktestTrade | None = None

    # On commence l'analyse à partir de l'indice ma_slow + 1
    start = ma_slow + 1

    for i in range(start, len(candles)):
        fast_prev, fast_curr = ma_f.iloc[i - 1], ma_f.iloc[i]
        slow_prev, slow_curr = ma_s.iloc[i - 1], ma_s.iloc[i]

        # Vérifier SL/TP si une position est ouverte
        if current_trade is not None:
            if current_trade.side == "BUY":
                # TP touché ?
                if highs[i] >= current_trade.tp:
                    current_trade.close(current_trade.tp, i, "TP")
                    trades.append(current_trade)
                    current_trade = None
                    continue
                # SL touché ?
                if lows[i] <= current_trade.sl:
                    current_trade.close(current_trade.sl, i, "SL")
                    trades.append(current_trade)
                    current_trade = None
                    continue
            else:  # SELL
                if lows[i] <= current_trade.tp:
                    current_trade.close(current_trade.tp, i, "TP")
                    trades.append(current_trade)
                    current_trade = None
                    continue
                if highs[i] >= current_trade.sl:
                    current_trade.close(current_trade.sl, i, "SL")
                    trades.append(current_trade)
                    current_trade = None
                    continue

        # Détecter signal de croisement
        signal = Signal.HOLD
        if fast_prev <= slow_prev and fast_curr > slow_curr:
            signal = Signal.BUY
        elif fast_prev >= slow_prev and fast_curr < slow_curr:
            signal = Signal.SELL

        price = closes[i]
        sl_dist = sl_pips * pip_value
        tp_dist = tp_pips * pip_value

        if signal == Signal.BUY:
            # Fermer une position SELL existante
            if current_trade and current_trade.side == "SELL":
                current_trade.close(price, i, "signal")
                trades.append(current_trade)
                current_trade = None
            # Ouvrir BUY si pas de position
            if current_trade is None:
                sl = round(price - sl_dist, 5)
                tp = round(price + tp_dist, 5)
                current_trade = BacktestTrade("BUY", price, i, sl, tp)

        elif signal == Signal.SELL:
            # Fermer une position BUY existante
            if current_trade and current_trade.side == "BUY":
                current_trade.close(price, i, "signal")
                trades.append(current_trade)
                current_trade = None
            # Ouvrir SELL si pas de position
            if current_trade is None:
                sl = round(price + sl_dist, 5)
                tp = round(price - tp_dist, 5)
                current_trade = BacktestTrade("SELL", price, i, sl, tp)

    # Fermer la position restante à la dernière bougie
    if current_trade is not None:
        current_trade.close(closes[-1], len(candles) - 1, "fin_backtest")
        trades.append(current_trade)

    return trades


def print_report(trades: list[BacktestTrade], symbol: str, num_candles: int):
    """Affiche un rapport détaillé du backtest."""
    print("\n" + "=" * 65)
    print(f"  📊  RAPPORT DE BACKTEST  –  {symbol}")
    print(f"  Bougies analysées : {num_candles}")
    print(f"  Stratégie : MA{config.MA_FAST} / MA{config.MA_SLOW}")
    print("=" * 65)

    if not trades:
        print("  Aucun trade exécuté pendant la période.")
        print("=" * 65)
        return

    total_pnl = sum(t.pnl for t in trades)
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    print(f"\n  Nombre de trades   : {len(trades)}")
    print(f"  ✅ Gagnants        : {len(wins)}")
    print(f"  ❌ Perdants        : {len(losses)}")
    print(f"  📈 Win rate        : {win_rate:.1f}%")
    print(f"  💰 PnL total (pts) : {total_pnl:+.5f}")

    if wins:
        best = max(t.pnl for t in wins)
        avg_win = sum(t.pnl for t in wins) / len(wins)
        print(f"  Meilleur trade     : +{best:.5f}")
        print(f"  Gain moyen         : +{avg_win:.5f}")

    if losses:
        worst = min(t.pnl for t in losses)
        avg_loss = sum(t.pnl for t in losses) / len(losses)
        print(f"  Pire trade         : {worst:.5f}")
        print(f"  Perte moyenne      : {avg_loss:.5f}")

    # Détail par sortie
    exits = {}
    for t in trades:
        exits[t.exit_reason] = exits.get(t.exit_reason, 0) + 1
    print(f"\n  Sorties par type :")
    for reason, count in exits.items():
        print(f"    {reason:15s} : {count}")

    print("\n  ── Détail des trades ──")
    for idx, t in enumerate(trades, 1):
        print(f"  #{idx:3d}  {t}")

    print("=" * 65)


def main():
    parser = argparse.ArgumentParser(description="Backtester TradeAI")
    parser.add_argument("--symbol", type=str, default=config.SYMBOL, help="Symbole à backtester")
    parser.add_argument("--period", type=int, default=config.CANDLE_PERIOD, help="Timeframe (minutes)")
    parser.add_argument("--candles", type=int, default=500, help="Nombre de bougies")
    parser.add_argument("--sl", type=int, default=config.STOP_LOSS_PIPS, help="Stop loss en pips")
    parser.add_argument("--tp", type=int, default=config.TAKE_PROFIT_PIPS, help="Take profit en pips")
    parser.add_argument("--offline", action="store_true", help="Utiliser des données simulées (sans API)")
    args = parser.parse_args()

    logger.info("Démarrage du backtest sur %s (%d bougies, période %d min)…",
                args.symbol, args.candles, args.period)

    # Source de données : API ou simulateur offline
    if args.offline:
        logger.info("💻 Mode offline – données de marché simulées")
        client = MarketSimulator(symbol=args.symbol)
    else:
        client = XTBClient()

    if not client.connect():
        logger.critical("Impossible de se connecter.")
        return

    try:
        candles = client.get_candles(args.symbol, args.period, count=args.candles)
        if not candles:
            logger.error("Aucune bougie récupérée. Vérifiez le symbole et la période.")
            return

        logger.info("📥 %d bougies téléchargées.", len(candles))

        trades = run_backtest(candles, config.MA_FAST, config.MA_SLOW, args.sl, args.tp)
        print_report(trades, args.symbol, len(candles))

    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
