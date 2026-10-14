# Stablecoin Peg & Pool Risk Monitor

An automated tool to track stablecoin prices, oracle delays, and pool balances across Ethereum.

---

## What It Does

The script watches three main stablecoins: **USDe**, **USDC**, and **USDT**:

* **Price and Oracle Spread:** Compares live DEX trading prices from DefiLlama with on-chain Chainlink feeds to spot pricing gaps and update delays.
* **Curve Pool Balance:** Checks coin balances in top Curve pools. When one coin fills more than 75% to 80% of a pool, it signals that people are dumping it to get out.
* **Alerts:** Triggers warnings if a price slips more than 1.5% off $1.00 or if pool balance gets too lopsided.

---

## Lending Market Comparison

How different protocols handle USDe risk:

| Rule | Aave V3 (Ethereum Core) | Morpho (Blue) | Compound V3 (Comet) |
| :--- | :--- | :--- | :--- |
| **Pool Setup** | One big shared pool for all coins | Separate 1-on-1 pairs and vaults | One main borrow coin per market |
| **Spillover Risk** | High. Unpaid USDe loans can hurt other coins in the pool | None. Losses stay locked inside that single USDe pair | Contained. Deposits stay guarded by the liquidation system |
| **Deposit and Borrow Limits** | Strict caps voted by the DAO (such as 80M supply / 72M borrow) | No protocol caps; each vault manager sets their own | Strict caps on collateral; open supply for the main borrow coin |
| **Borrow Power (Max LTV)** | 72% | Set per market (often 86% or 91.5%) | Fixed number set by governance vote |
| **Liquidation Point** | 75% | Hits when loan ratio passes the pair limit | Fixed cutoff set by governance vote |
| **Price Feed Source** | Standard Chainlink feeds | Market creator picks (Chainlink, custom, or flat $1.00) | Standard Chainlink feeds |

---

## How It Works

* **Stack:** Python 3.10+, Web3.py, and Requests.
* **Data:** Chainlink smart contracts via public RPC, DefiLlama API, and Curve registry API.
* **Runs Automatically:** Executes every hour through GitHub Actions (`.github/workflows/monitor.yml`).
* **Storage:** Writes timestamped rows straight into `peg_monitor_log.csv` and updates `usde_risk_chart.png`.

---

## What's Next

* Compare live collateral and borrow rules across more lending apps.
* Add deeper chart options to track price spreads and pool imbalances over longer windows.
