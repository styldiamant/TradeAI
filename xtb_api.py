"""
============================================================
  xtb_api.py  –  Client Python pour l'API XTB (xAPI)
============================================================
Utilise des WebSockets pour communiquer avec le serveur XTB.
Documentation officielle : http://developers.xstore.pro/documentation/
============================================================
"""

import json
import time
import ssl
import logging
from typing import Optional

import websocket  # websocket-client

import config

logger = logging.getLogger("XTB_API")


class XTBClient:
    """
    Client bas-niveau pour l'API XTB (xAPI).
    Gère la connexion, l'envoi de commandes et la réception de réponses.
    """

    def __init__(self):
        self.ws: Optional[websocket.WebSocket] = None
        self.stream_session_id: Optional[str] = None
        self._connected: bool = False

    # ── Connexion / Déconnexion ───────────────────────────────

    def connect(self) -> bool:
        """
        Ouvre la connexion WebSocket et s'authentifie auprès de XTB.
        Retourne True si la connexion est établie avec succès.
        """
        try:
            logger.info("Connexion au serveur XTB (%s)…", config.XTB_MODE)
            self.ws = websocket.create_connection(
                config.SERVER_MAIN,
                sslopt={"cert_reqs": ssl.CERT_NONE},
                timeout=10,
            )
            # Envoi de la commande login
            response = self._send_command("login", {
                "userId": config.XTB_USER_ID,
                "password": config.XTB_PASSWORD,
            })

            if response.get("status") is True:
                self.stream_session_id = response.get("streamSessionId")
                self._connected = True
                logger.info("✅ Connecté avec succès (sessionId: %s)", self.stream_session_id)
                return True
            else:
                error_code = response.get("errorCode", "UNKNOWN")
                error_desc = response.get("errorDescr", "")
                logger.error("❌ Échec de connexion : %s – %s", error_code, error_desc)
                return False

        except Exception as exc:
            logger.error("❌ Erreur de connexion : %s", exc)
            return False

    def disconnect(self):
        """Ferme proprement la connexion WebSocket."""
        if self.ws:
            try:
                self._send_command("logout")
            except Exception:
                pass
            finally:
                self.ws.close()
                self._connected = False
                logger.info("Déconnecté du serveur XTB.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── Envoi / Réception de commandes ────────────────────────

    def _send_command(self, command: str, arguments: dict | None = None) -> dict:
        """
        Envoie une commande JSON au serveur xAPI et retourne la réponse.
        """
        payload: dict = {"command": command}
        if arguments:
            payload["arguments"] = arguments

        raw = json.dumps(payload)
        self.ws.send(raw)
        response_raw = self.ws.recv()
        return json.loads(response_raw)

    # ── Données marché ────────────────────────────────────────

    def get_symbol(self, symbol: str) -> dict:
        """
        Retourne les informations d'un symbole (spread, pip, etc.).
        """
        resp = self._send_command("getSymbol", {"symbol": symbol})
        if resp.get("status"):
            return resp.get("returnData", {})
        logger.warning("getSymbol échoué : %s", resp)
        return {}

    def get_current_price(self, symbol: str) -> dict:
        """
        Retourne le prix bid/ask courant d'un symbole.
        Utilise getSymbol qui contient bid et ask.
        Retourne : {"bid": float, "ask": float, "spread": float}
        """
        data = self.get_symbol(symbol)
        if data:
            return {
                "bid": data.get("bid", 0.0),
                "ask": data.get("ask", 0.0),
                "spread": data.get("spreadRaw", 0.0),
                "pip": data.get("pipsPrecision", 4),
            }
        return {"bid": 0.0, "ask": 0.0, "spread": 0.0, "pip": 4}

    def get_candles(self, symbol: str, period: int, count: int = 100) -> list[dict]:
        """
        Récupère les dernières bougies (candlesticks) via getChartLastRequest.
        
        Paramètres :
            symbol  – symbole de l'actif (ex. "EURUSD")
            period  – timeframe en minutes (1, 5, 15, 30, 60, 240, 1440…)
            count   – nombre de bougies souhaitées (approximatif)
        
        Retourne une liste de dicts : [{open, close, high, low, vol, ctm}, …]
        """
        # On demande des bougies depuis (maintenant - count * period) minutes
        start_time = int((time.time() - count * period * 60) * 1000)

        resp = self._send_command("getChartLastRequest", {
            "info": {
                "period": period,
                "start": start_time,
                "symbol": symbol,
            }
        })

        if resp.get("status"):
            raw = resp.get("returnData", {})
            digits = raw.get("digits", 5)
            rate_infos = raw.get("rateInfos", [])
            candles = []
            for r in rate_infos:
                candles.append({
                    "ctm": r["ctm"],
                    "open": r["open"] / (10 ** digits),
                    "close": (r["open"] + r["close"]) / (10 ** digits),
                    "high": (r["open"] + r["high"]) / (10 ** digits),
                    "low": (r["open"] + r["low"]) / (10 ** digits),
                    "vol": r.get("vol", 0),
                })
            return candles
        else:
            logger.warning("getChartLastRequest échoué : %s", resp)
            return []

    # ── Trading ───────────────────────────────────────────────

    def open_trade(
        self,
        symbol: str,
        cmd: int,          # 0 = BUY, 1 = SELL
        volume: float,
        price: float,
        sl: float = 0.0,
        tp: float = 0.0,
        comment: str = "TradeAI",
    ) -> dict:
        """
        Ouvre une position via tradeTransaction.
        
        cmd : 0 = BUY, 1 = SELL
        Retourne la réponse du serveur.
        """
        trade_info = {
            "cmd": cmd,
            "customComment": comment,
            "expiration": 0,
            "offset": 0,
            "order": 0,
            "price": price,
            "sl": sl,
            "symbol": symbol,
            "tp": tp,
            "type": 0,          # 0 = OPEN
            "volume": volume,
        }
        resp = self._send_command("tradeTransaction", {"tradeTransInfo": trade_info})
        if resp.get("status"):
            order_id = resp.get("returnData", {}).get("order", 0)
            logger.info("✅ Ordre ouvert (orderId=%s)", order_id)
            return resp.get("returnData", {})
        else:
            logger.error("❌ Échec ouverture ordre : %s", resp)
            return {}

    def close_trade(self, order_id: int, symbol: str, cmd: int, volume: float, price: float) -> dict:
        """
        Ferme une position existante.
        Pour fermer un BUY (cmd=0) on envoie cmd=0 + type=2 (CLOSE).
        """
        trade_info = {
            "cmd": cmd,
            "customComment": "TradeAI_close",
            "expiration": 0,
            "offset": 0,
            "order": order_id,
            "price": price,
            "sl": 0.0,
            "symbol": symbol,
            "tp": 0.0,
            "type": 2,          # 2 = CLOSE
            "volume": volume,
        }
        resp = self._send_command("tradeTransaction", {"tradeTransInfo": trade_info})
        if resp.get("status"):
            logger.info("✅ Position fermée (orderId=%s)", order_id)
            return resp.get("returnData", {})
        else:
            logger.error("❌ Échec fermeture position : %s", resp)
            return {}

    def get_open_trades(self) -> list[dict]:
        """Retourne la liste des trades ouverts."""
        resp = self._send_command("getTrades", {"openedOnly": True})
        if resp.get("status"):
            return resp.get("returnData", [])
        return []

    # ── Informations du compte ────────────────────────────────

    def get_margin_level(self) -> dict:
        """Retourne les informations de marge du compte."""
        resp = self._send_command("getMarginLevel")
        if resp.get("status"):
            return resp.get("returnData", {})
        return {}

    def get_server_time(self) -> int:
        """Retourne le timestamp du serveur en millisecondes."""
        resp = self._send_command("getServerTime")
        if resp.get("status"):
            return resp.get("returnData", {}).get("time", 0)
        return 0

    # ── Keep-alive (ping) ─────────────────────────────────────

    def ping(self):
        """Envoie un ping pour maintenir la connexion active."""
        try:
            self._send_command("ping")
        except Exception as exc:
            logger.warning("Ping échoué : %s", exc)
            self._connected = False
