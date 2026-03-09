# 🤖 TradeAI – Robot de Trading Automatique pour XTB

Robot de trading algorithmique en Python qui se connecte à l'API XTB (xAPI) pour analyser le marché et passer des ordres automatiquement à l'aide d'une stratégie de croisement de moyennes mobiles.

---

## 📁 Structure du projet

```
TradeAI/
├── main.py            # Boucle principale du robot
├── xtb_api.py         # Client API XTB (WebSocket / xAPI)
├── strategy.py        # Stratégie de trading (moyennes mobiles)
├── config.py          # Configuration centralisée (lit le .env)
├── backtest.py        # Backtester simple
├── requirements.txt   # Dépendances Python
├── .env.example       # Modèle de fichier de configuration
├── .env               # ⚠️ Vos identifiants (non versionné)
└── README.md          # Ce fichier
```

---

## ⚡ Installation rapide

### ⚠️ Situation de l'API XTB (important)

**L'API publique XTB (`ws.xtb.com`) a été désactivée le 14 mars 2025.**

La même API (xAPI) reste disponible via **X Open Hub** (`ws.xapi.pro`), une filiale de XTB :

1. Créez un **compte démo gratuit** sur **https://xopenhub.pro/try-demo/**
2. Utilisez le numéro de compte et le mot de passe reçus dans votre `.env`
3. Le robot est configuré par défaut sur `ws.xapi.pro`

> Les comptes réels XTB ne fonctionnent pas sur X Open Hub. Seuls les comptes démo X Open Hub et les comptes démo XTB (créés avant mars 2025) sont supportés.

Si XTB réactive un jour son API, changez simplement `XTB_HOST=ws.xtb.com` dans `.env`.

### 1. Cloner le projet

```bash
git clone <votre-repo> TradeAI
cd TradeAI
```

### 2. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 3. Configurer les identifiants

```bash
copy .env.example .env     # Windows
# cp .env.example .env     # Linux/Mac
```

Ouvrez `.env` et remplissez vos identifiants XTB :

```env
XTB_USER_ID=votre_identifiant
XTB_PASSWORD=votre_mot_de_passe
XTB_MODE=demo
SYMBOL=EURUSD
```

---

## 🚀 Lancer le robot

### Mode Paper Trading (simulation – aucun ordre réel)

```bash
python main.py --paper
```

### Mode Live Trading (ordres réels)

```bash
python main.py --live
```

> ⚠️ **Attention** : En mode live, le robot passera de vrais ordres sur votre compte XTB. Utilisez d'abord le mode **demo** de XTB et le mode **paper** du robot.

---

## 📊 Backtester

Le backtester télécharge les bougies historiques depuis XTB et simule la stratégie :

```bash
# Backtest par défaut (EURUSD, 500 bougies, 5 min)
python backtest.py

# Backtest personnalisé
python backtest.py --symbol GASOLINE --period 15 --candles 1000 --sl 30 --tp 60
```

### Options du backtester

| Option      | Description                     | Défaut          |
| ----------- | ------------------------------- | --------------- |
| `--symbol`  | Symbole de l'actif              | Valeur du .env  |
| `--period`  | Timeframe en minutes            | 5               |
| `--candles` | Nombre de bougies historiques   | 500             |
| `--sl`      | Stop Loss en pips               | 50              |
| `--tp`      | Take Profit en pips             | 100             |

---

## 🧠 Stratégie

Le robot utilise un **croisement de moyennes mobiles** (Moving Average Crossover) :

- **MA rapide** (par défaut MA20) – réagit vite aux mouvements de prix
- **MA lente** (par défaut MA50) – filtre le bruit du marché

### Signaux

| Condition                              | Signal    |
| -------------------------------------- | --------- |
| MA20 croise **au-dessus** de MA50      | **BUY**   |
| MA20 croise **en dessous** de MA50     | **SELL**  |
| Pas de croisement                      | **HOLD**  |

### Gestion du risque

Chaque trade est protégé par :
- **Stop Loss** automatique (configurable en pips)
- **Take Profit** automatique (configurable en pips)
- **Volume** configurable (taille du lot)

---

## ⚙️ Configuration complète

Toutes les variables sont dans le fichier `.env` :

| Variable            | Description                      | Défaut     |
| ------------------- | -------------------------------- | ---------- |
| `XTB_USER_ID`       | Identifiant (numéro de compte)   | –          |
| `XTB_PASSWORD`       | Mot de passe                     | –          |
| `XTB_HOST`           | Serveur API                      | `ws.xapi.pro` |
| `XTB_MODE`           | `demo` ou `real`                 | `demo`     |
| `SYMBOL`            | Actif à trader                   | `EURUSD`   |
| `MA_FAST`           | Période MA rapide                | `20`       |
| `MA_SLOW`           | Période MA lente                 | `50`       |
| `VOLUME`            | Taille du lot                    | `0.01`     |
| `STOP_LOSS_PIPS`    | Stop Loss en pips                | `50`       |
| `TAKE_PROFIT_PIPS`  | Take Profit en pips              | `100`      |
| `LOOP_INTERVAL`     | Intervalle analyse (secondes)    | `30`       |
| `CANDLE_PERIOD`     | Timeframe bougies (minutes)      | `5`        |
| `PAPER_TRADING`     | Mode simulation                  | `true`     |

---

## 📝 Logs

Le robot affiche en console et enregistre dans `tradeai.log` :
- Le prix actuel (bid / ask / spread)
- Les valeurs des moyennes mobiles
- Le signal détecté (BUY / SELL / HOLD)
- Les ordres envoyés ou simulés

---

## 🔒 Sécurité

- Les identifiants sont stockés dans `.env` (jamais dans le code source)
- Le fichier `.env` est exclu du versionnement via `.gitignore`
- Le mode `PAPER_TRADING=true` est activé par défaut

---

## 🏗️ Architecture technique

```
main.py
  │
  ├── config.py       ← Lit le .env, expose les constantes
  │
  ├── xtb_api.py      ← Connexion WebSocket, commandes xAPI
  │     ├── connect() / disconnect()
  │     ├── get_current_price()
  │     ├── get_candles()
  │     ├── open_trade() / close_trade()
  │     └── get_open_trades()
  │
  └── strategy.py     ← Analyse des bougies
        ├── compute_moving_averages()
        ├── detect_crossover()
        └── analyze() → Signal (BUY/SELL/HOLD)
```

---

## ⚠️ Avertissement

Ce robot est fourni **à titre éducatif uniquement**. Le trading sur les marchés financiers comporte des risques significatifs de perte en capital. Testez toujours en mode démo avant d'utiliser de l'argent réel. L'auteur décline toute responsabilité en cas de pertes financières.
