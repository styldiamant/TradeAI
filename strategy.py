"""
============================================================
  strategy.py  –  Stratégie de croisement de moyennes mobiles
============================================================
Signal :
    • MA rapide (20) croise AU-DESSUS de MA lente (50) → BUY
    • MA rapide (20) croise EN DESSOUS de MA lente (50) → SELL
    • Sinon → HOLD (ne rien faire)
============================================================
"""

import logging
from enum import Enum

import numpy as np
import pandas as pd

import config

logger = logging.getLogger("STRATEGY")


class Signal(Enum):
    """Signaux possibles émis par la stratégie."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


def compute_moving_averages(closes: list[float]) -> tuple[pd.Series, pd.Series]:
    """
    Calcule les deux moyennes mobiles (rapide et lente) à partir
    d'une liste de cours de clôture.

    Retourne (ma_fast, ma_slow) sous forme de pandas Series.
    """
    series = pd.Series(closes)
    ma_fast = series.rolling(window=config.MA_FAST).mean()
    ma_slow = series.rolling(window=config.MA_SLOW).mean()
    return ma_fast, ma_slow


def detect_crossover(ma_fast: pd.Series, ma_slow: pd.Series) -> Signal:
    """
    Détecte un croisement entre la MA rapide et la MA lente
    en comparant les deux dernières valeurs.

    Logique :
        - Si la MA rapide vient de passer au-dessus de la MA lente → BUY
        - Si la MA rapide vient de passer en dessous de la MA lente → SELL
        - Sinon → HOLD
    """
    # On a besoin d'au moins 2 valeurs valides
    if ma_fast.dropna().shape[0] < 2 or ma_slow.dropna().shape[0] < 2:
        logger.debug("Pas assez de données pour détecter un croisement.")
        return Signal.HOLD

    # Dernières et avant-dernières valeurs
    fast_prev, fast_curr = ma_fast.iloc[-2], ma_fast.iloc[-1]
    slow_prev, slow_curr = ma_slow.iloc[-2], ma_slow.iloc[-1]

    # Vérifier qu'il n'y a pas de NaN
    if np.isnan(fast_prev) or np.isnan(fast_curr) or np.isnan(slow_prev) or np.isnan(slow_curr):
        return Signal.HOLD

    # Croisement haussier : MA rapide passe au-dessus de MA lente
    if fast_prev <= slow_prev and fast_curr > slow_curr:
        logger.info("🔼 Croisement haussier détecté (MA%d > MA%d)", config.MA_FAST, config.MA_SLOW)
        return Signal.BUY

    # Croisement baissier : MA rapide passe en dessous de MA lente
    if fast_prev >= slow_prev and fast_curr < slow_curr:
        logger.info("🔽 Croisement baissier détecté (MA%d < MA%d)", config.MA_FAST, config.MA_SLOW)
        return Signal.SELL

    return Signal.HOLD


def analyze(candles: list[dict]) -> Signal:
    """
    Point d'entrée principal de la stratégie.
    Reçoit une liste de bougies [{open, close, high, low, vol, ctm}, …]
    et retourne un Signal (BUY / SELL / HOLD).
    """
    if len(candles) < config.MA_SLOW + 2:
        logger.warning(
            "Pas assez de bougies (%d) pour calculer MA%d. Minimum requis : %d.",
            len(candles), config.MA_SLOW, config.MA_SLOW + 2,
        )
        return Signal.HOLD

    closes = [c["close"] for c in candles]

    ma_fast, ma_slow = compute_moving_averages(closes)

    # Log des dernières valeurs
    logger.info(
        "MA%d = %.5f  |  MA%d = %.5f",
        config.MA_FAST, ma_fast.iloc[-1],
        config.MA_SLOW, ma_slow.iloc[-1],
    )

    signal = detect_crossover(ma_fast, ma_slow)
    logger.info("Signal de la stratégie : %s", signal.value)
    return signal
