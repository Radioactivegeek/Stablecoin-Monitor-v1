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
## Live-Fire Validation: October 30, 2026 Binance Shock

> **TL;DR:** During the ~$6.3B Binance hack on Oct 29–30, 2026, this automated pipeline caught the on-chain USDe sell-off, fired a `LIQUIDITY_WARNING` at **78.14% pool dominance**, and logged an **18.5-hour stale oracle freeze**—all without manual input.

### What Happened
After the Binance hot-wallet breach, traders rushed to exit USDe because Ethena hedges on Binance (even though its collateral sits with off-exchange custodians). That sell-off skewed the Curve `USDe-USDC` pool and froze the on-chain oracle below peg for 18.5 hours.

### Baseline vs. Peak Stress (`peg_monitor_log.csv`, 179 snapshots)

| Metric | Baseline (Oct 12 – Nov 23) | Oct 30 Peak Stress | What It Meant |
| :--- | :--- | :--- | :--- |
| **Pool Dominance (`USDe-USDC`)** | 56.23% avg | **78.14%** (01:01 UTC) | Crossed 75% limit → `LIQUIDITY_WARNING` fired |
| **Spot USDe Price** | $0.9993 avg | **$0.9975** (01:01 UTC) | Mild 25 bps wobble—not a real depeg |
| **On-Chain Oracle** | $0.9994 avg | **$0.9944** (frozen ~18.5h) | Stuck below $0.9950 until heartbeat refreshed at 23:49 UTC |
| **Oracle Spread** | 0.03% avg | **0.41%** (19:24 UTC) | Widened after spot recovered to $0.9985 while oracle lagged |

![USDe Risk Telemetry — Oct 30 Shock](image.png)

### How This Tool Prevents Losses
* **Catches Bad Debt Early:** In the March 2026 Resolv (USR) hack, a stuck oracle let attackers borrow real USDC against worthless collateral. Tracking DEX pool skew and oracle spread together flags that exact gap before vaults get drained.
* **Stops Unfair Liquidations:** On Oct 30, the oracle stayed stuck at `$0.9944` for 18.5 hours even after USDe recovered to `$0.9985`. In high-LTV vaults (like Morpho at 86%–91.5% LLTV), that stale discount can liquidate healthy borrowers. This monitor spots the freeze immediately.
* **Prevents Panic Freezes:** Pairing a small ~$491K canary pool (`USDe-USDC`) with spot price showed right away that the 78% skew was just a 25 bps liquidity dip—not insolvency—so protocols don't waste time or revenue pausing markets over a false alarm.
---

## What's Next

* Compare live collateral and borrow rules across more lending apps.
* Add deeper chart options to track price spreads and pool imbalances over longer windows.
