# 📈 Polymarket Wallet Tracker (Free Version)

A high-speed, non-blocking tracker that monitors a specific target wallet on Polymarket in real-time. 

**This is the Free Version.** It does NOT require a private key and cannot execute real trades. Instead, it runs in **Simulation Mode**, logging "Paper Trades" to show you the Profit/Loss you *would* have made if you had followed the target.

## ✨ Features
- **Real-Time Tracking:** Polls the target wallet every 0.5s for new positions.
- **Orderbook Simulation:** Checks real Polymarket liquidity to give accurate "paper fill" prices (not just the price the target got).
- **PnL Reports:** Prints a detailed "Billionaire PnL Report" to the console showing how your simulated portfolio is performing.
- **Safe:** No wallet connection required.

## 💎 Paid Version
If you want the **Paid Version** (which connects to your wallet, signs transactions, and auto-executes trades live), please contact me:

- **X (Twitter):** [https://x.com/ArashStock](https://x.com/ArashStock)
- **Email:** [yasii0073000@yahoo.com](mailto:yasii0073000@yahoo.com)

I will let you know the details.

## 🛠 Prerequisites

You need **Python 3.9+** installed.

## 📦 Installation

1. Clone or download this repository.
2. Install the required dependencies:

```bash
pip install py-clob-client eth-account requests websockets eth-abi eth-utils nest_asyncio web3
```
🚀 How to Run
Open free_tracker.py in your code editor.

(Optional) Change the TARGET_WALLET variable to the address you want to stalk.

Run the script:

bash
python free_tracker.py
⚙️ Configuration
Inside the script, you can tweak the Simulation Settings:

MY_BANKROLL: Your simulated starting cash (e.g., $1000).

TARGET_ESTIMATED_BANKROLL: The target's bankroll (used to calculate bet ratio).

USE_RATIO: If True, your bet size scales with the target's bet size.

MY_FIXED_BET_SIZE: If USE_RATIO is False, uses this fixed $ amount per trade.

⚠️ Disclaimer
This software is for educational purposes only. The "Free Version" creates no financial risk as it does not execute trades, but please verify all logic before upgrading to any paid/execution versions.
