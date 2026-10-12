# Stablecoin Peg & Pool Risk Monitor

An automated, institutional-grade risk telemetry engine designed to detect stablecoin peg dislocations, oracle lag, and liquidity concentration across Ethereum DeFi protocols.

---

## What It Does

The engine monitors core stablecoin assets (**USDe**, **USDC**, and **USDT**) to identify systemic insolvency vectors and latency arbitrage conditions:

* **Oracle Latency & Spread Tracking:** Compares live aggregated secondary DEX spot prices (via DefiLlama) against real-time on-chain Chainlink Oracle responses to measure pricing divergence, heartbeat lag, and oracle arbitrage windows.
* **Curve Pool Invariant & Dominance Monitoring:** Tracks token inventory across primary Curve Finance liquidity pools to detect breaches of the 80/20 balance invariant. Heavy reserve skew (>75–80%) signals liquidity cliffs and exiting smart money prior to oracle updates.
* **Automated Risk Alerting:** Flags `DEPEG_WARNING` if spot prices deviate beyond threshold bounds (>1.5%) and triggers `LIQUIDITY_WARNING` when single-asset pool dominance signals liquidity exhaustion.

---

## Architecture & Telemetry Pipeline

* **Core Stack:** Python 3.10+, [Web3.py](https://github.com/ethereum/web3.py), and [Requests](https://requests.readthedocs.io/).
* **Data Sources:** Direct Ethereum JSON-RPC nodes (Chainlink Aggregator V3 contracts), DefiLlama Coins API, and Curve Finance registry APIs.
* **Autonomous Scheduling:** Runs hourly via GitHub Actions workflow (`.github/workflows/monitor.yml`).
* **Persistence:** Appends timestamped observations (asset, spot price, peg deviation, oracle price, spread, pool TVL, pool dominance, and alerts) directly to `peg_monitor_log.csv`.

---

## Future Upgrades (Under Active Development)

This repository is under active development. Upcoming releases will introduce:

* **Cross-Protocol Risk Parameter Comparison Matrix:** Automated benchmarking of collateral and borrow parameters across lending markets (Aave V3 vs. Morpho Blue vs. Compound V3), tracking supply caps, borrow caps, liquidation thresholds (LLTV/LT), and liquidation bonuses.
* **Automated Historical Trend Charting:** A dedicated Python analysis module (`pandas` / `matplotlib`) to visualize time-series peg deviation, oracle spread deltas, and Curve reserve skew directly from `peg_monitor_log.csv`.

