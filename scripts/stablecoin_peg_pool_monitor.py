"""Monitor stablecoin peg deviations and Curve pool concentration.

Upgrades (v2.0):
  1. Pool Name & TVL columns in both console output and CSV log.
  2. Yield-bearing tokens (sUSDS) no longer show a misleading peg
     deviation against $1.00; displayed as 'Yield Bearing' instead.
  4. Top 3 Curve pools per asset (by TVL) instead of only one, giving
     a complete liquidity distribution picture across venues.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import requests
from web3 import Web3


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
COINS_URL = "https://coins.llama.fi/prices/current/"
CURVE_REGISTRY_URLS = (
    "https://api.curve.fi/api/getPools/ethereum/main",
    "https://api.curve.fi/api/getPools/ethereum/factory-stable-ng",
    "https://api.curve.fi/api/getPools/ethereum/factory",
)
LOG_PATH = Path(__file__).resolve().parent.parent / "peg_monitor_log.csv"

DEPEG_THRESHOLD_PERCENT = Decimal("1.5")
LIQUIDITY_DOMINANCE_THRESHOLD_PERCENT = Decimal("75")
REQUEST_TIMEOUT_SECONDS = 30
TOP_POOLS_PER_ASSET = 3
ORACLE_SPREAD_THRESHOLD_PERCENT = Decimal("0.5")
ETHEREUM_RPC_URLS = (
    "https://ethereum-rpc.publicnode.com",
    "https://rpc.flashbots.net",
    "https://eth.drpc.org",
)

CHAINLINK_ABI = [
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"internalType": "uint80", "name": "roundId", "type": "uint80"},
            {"internalType": "int256", "name": "answer", "type": "int256"},
            {"internalType": "uint256", "name": "startedAt", "type": "uint256"},
            {"internalType": "uint256", "name": "updatedAt", "type": "uint256"},
            {"internalType": "uint80", "name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

CHAINLINK_FEEDS = {
    "USDe": "0xcC16f670129f965b396f2e81312F6e339FFDB18e",
    "USDC": "0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6",
    "USDT": "0x9c41663bB8d6800c8050E2Fbf98E86AD01c973e3",
}

ASSETS = {
    "USDe": {
        "address": "0x4c9EDD5852cd905f086C759E8383e09bff1E68B3",
        "decimals": 18,
        "yield_bearing": False,
    },
    "USDC": {
        "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "decimals": 6,
        "yield_bearing": False,
    },
    "USDT": {
        "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "decimals": 6,
        "yield_bearing": False,
    },
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PoolInfo:
    """Curve pool dominance snapshot for one monitored asset."""

    name: str
    tvl_usd: Decimal
    dominance_percent: Decimal
    dominance_alert: bool  # True when dominance > threshold


@dataclass(frozen=True)
class AssetObservation:
    """Full observation for a single monitored stablecoin."""

    timestamp: str
    asset: str
    price: Decimal
    peg_deviation_percent: Decimal | None  # None for yield-bearing tokens
    oracle_price: Decimal | None
    oracle_spread_percent: Decimal | None
    is_yield_bearing: bool
    pools: tuple[PoolInfo, ...]
    active_alerts: str  # Semicolon-separated alert codes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_decimal(value: Any, fallback: str = "0") -> Decimal:
    """Convert *value* to ``Decimal``, returning *fallback* on failure."""
    if value is None:
        return Decimal(fallback)
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(fallback)


def _format_peg_dev(obs: AssetObservation) -> str:
    """Human-readable peg deviation string."""
    if obs.is_yield_bearing:
        premium = (obs.price - Decimal("1")) * Decimal("100")
        sign = "+" if premium >= 0 else ""
        return f"Yield Bearing ({sign}{premium:.2f}%)"
    if obs.peg_deviation_percent is not None:
        return f"{obs.peg_deviation_percent:.4f}%"
    return "N/A"


def _format_tvl(tvl: Decimal) -> str:
    """Format TVL as human-readable ($1.2M, $450.3K, etc.)."""
    if tvl >= 1_000_000:
        return f"${tvl / 1_000_000:,.1f}M"
    if tvl >= 1_000:
        return f"${tvl / 1_000:,.1f}K"
    return f"${tvl:,.0f}"


def get_json(session: requests.Session, url: str) -> dict[str, Any]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected a JSON object from {url}.")
    return payload


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------
def fetch_prices(session: requests.Session) -> dict[str, Decimal]:
    coin_ids = ",".join(
        f"ethereum:{details['address']}" for details in ASSETS.values()
    )
    payload = get_json(session, f"{COINS_URL}{coin_ids}")
    coins = payload.get("coins")
    if not isinstance(coins, dict):
        raise RuntimeError("DefiLlama response did not contain a coins object.")

    prices: dict[str, Decimal] = {}
    for asset, details in ASSETS.items():
        key = f"ethereum:{details['address']}"
        coin = coins.get(key)
        if not isinstance(coin, dict) or "price" not in coin:
            raise RuntimeError(f"DefiLlama returned no price for {asset}.")
        try:
            price = Decimal(str(coin["price"]))
        except (InvalidOperation, TypeError) as exc:
            raise RuntimeError(f"Invalid DefiLlama price for {asset}.") from exc
        if price <= 0:
            raise RuntimeError(
                f"DefiLlama returned a non-positive price for {asset}."
            )
        prices[asset] = price
    return prices


def fetch_oracle_prices(
    web3: Web3,
) -> dict[str, Decimal | None]:
    oracle_prices: dict[str, Decimal | None] = {}
    for asset, address in CHAINLINK_FEEDS.items():
        try:
            checksum_address = web3.to_checksum_address(address)
            contract = web3.eth.contract(
                address=checksum_address,
                abi=CHAINLINK_ABI,
            )
            decimals = int(contract.functions.decimals().call())
            round_data = contract.functions.latestRoundData().call()
            answer = int(round_data[1])
            if answer <= 0:
                raise RuntimeError("Chainlink returned a non-positive answer.")
            oracle_prices[asset] = Decimal(answer) / (Decimal(10) ** decimals)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to fetch Chainlink oracle price for {asset}."
            ) from exc
    return oracle_prices


def connect_to_ethereum() -> Web3:
    for rpc_url in ETHEREUM_RPC_URLS:
        provider = Web3.HTTPProvider(
            rpc_url,
            request_kwargs={"timeout": REQUEST_TIMEOUT_SECONDS},
        )
        web3 = Web3(provider)
        if web3.is_connected():
            return web3
    raise RuntimeError(
        "Could not connect to any configured Ethereum RPC: "
        + ", ".join(ETHEREUM_RPC_URLS)
    )


def fetch_curve_pools(session: requests.Session) -> list[dict[str, Any]]:
    pools: list[dict[str, Any]] = []
    for url in CURVE_REGISTRY_URLS:
        payload = get_json(session, url)
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(
            data.get("poolData"), list
        ):
            raise RuntimeError(
                f"Curve response did not contain data.poolData: {url}"
            )
        pools.extend(
            pool for pool in data["poolData"] if isinstance(pool, dict)
        )
    return pools


# ---------------------------------------------------------------------------
# Pool analysis (Upgrade #4: multi-pool per asset)
# ---------------------------------------------------------------------------
def select_top_pools(
    pools: list[dict[str, Any]],
    top_n: int = TOP_POOLS_PER_ASSET,
) -> dict[str, list[dict[str, Any]]]:
    """Return the top-N highest TVL Curve pools containing each asset."""
    candidates: dict[str, list[dict[str, Any]]] = {}
    addresses = {
        details["address"].lower(): asset for asset, details in ASSETS.items()
    }

    for pool in pools:
        coins = pool.get("coins")
        if not isinstance(coins, list):
            continue
        present_assets = {
            addresses[str(coin.get("address", "")).lower()]
            for coin in coins
            if isinstance(coin, dict)
            and str(coin.get("address", "")).lower() in addresses
        }
        for asset in present_assets:
            candidates.setdefault(asset, []).append(pool)

    # Sort by TVL descending and keep top N
    for asset in candidates:
        candidates[asset] = sorted(
            candidates[asset],
            key=lambda p: _safe_decimal(p.get("usdTotal")),
            reverse=True,
        )[:top_n]

    return candidates


def calculate_pool_info(
    pool: dict[str, Any],
    asset: str,
) -> PoolInfo:
    """Calculate dominance and extract metadata for a single pool."""
    target_address = ASSETS[asset]["address"].lower()
    coins = pool.get("coins")
    if not isinstance(coins, list):
        raise RuntimeError(f"Curve pool for {asset} has no coin data.")

    balances: list[Decimal] = []
    target_balance: Decimal | None = None
    for coin in coins:
        if not isinstance(coin, dict):
            continue
        try:
            balance = Decimal(str(coin["poolBalance"])) / (
                Decimal(10) ** int(coin["decimals"])
            )
        except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Invalid Curve balance in pool for {asset}."
            ) from exc
        if balance < 0:
            raise RuntimeError(
                f"Negative Curve balance in pool for {asset}."
            )
        balances.append(balance)
        if str(coin.get("address", "")).lower() == target_address:
            target_balance = balance

    total_balance = sum(balances, Decimal("0"))
    if target_balance is None or total_balance <= 0:
        raise RuntimeError(f"Could not calculate dominance for {asset}.")

    dominance = target_balance / total_balance * Decimal("100")
    pool_name = str(
        pool.get("name")
        or pool.get("symbol")
        or pool.get("address", "Unknown")
    )
    tvl = _safe_decimal(pool.get("usdTotal"))
    is_alert = dominance > LIQUIDITY_DOMINANCE_THRESHOLD_PERCENT

    return PoolInfo(
        name=pool_name,
        tvl_usd=tvl,
        dominance_percent=dominance,
        dominance_alert=is_alert,
    )


# ---------------------------------------------------------------------------
# Observation building (Upgrades #1, #2, #4 integrated)
# ---------------------------------------------------------------------------
def build_observations(
    prices: dict[str, Decimal],
    oracle_prices: dict[str, Decimal | None],
    top_pools: dict[str, list[dict[str, Any]]],
    timestamp: str,
) -> list[AssetObservation]:
    observations: list[AssetObservation] = []

    for asset, details in ASSETS.items():
        is_yield = details.get("yield_bearing", False)
        alerts: list[str] = []

        # Upgrade #2: Yield-bearing tokens don't have a $1.00 peg.
        # sUSDS accrues yield and naturally trades above $1.00.
        # Only alert if it drops below $0.99 (catastrophic depeg).
        if is_yield:
            peg_dev: Decimal | None = None
            if prices[asset] < Decimal("0.99"):
                alerts.append("DEPEG_WARNING")
        else:
            peg_dev = abs(prices[asset] - Decimal("1")) * Decimal("100")
            if peg_dev > DEPEG_THRESHOLD_PERCENT:
                alerts.append("DEPEG_WARNING")

        oracle_price = oracle_prices.get(asset)
        oracle_spread: Decimal | None = None
        if oracle_price is not None:
            oracle_spread = (
                abs(oracle_price - prices[asset]) / oracle_price * Decimal("100")
            )
            if oracle_spread > ORACLE_SPREAD_THRESHOLD_PERCENT:
                alerts.append("ORACLE_ARBITRAGE_WARNING")

        # Upgrade #4: Analyze multiple pools per asset
        asset_pools = top_pools.get(asset, [])
        if not asset_pools:
            alerts.append("LIQUIDITY_DATA_UNAVAILABLE")
            pool_infos: tuple[PoolInfo, ...] = ()
        else:
            infos: list[PoolInfo] = []
            for raw_pool in asset_pools:
                try:
                    info = calculate_pool_info(raw_pool, asset)
                    infos.append(info)
                    if info.dominance_alert:
                        label = (
                            info.name[:20]
                            if len(info.name) > 20
                            else info.name
                        )
                        alerts.append(f"LIQUIDITY_WARNING({label})")
                except RuntimeError:
                    # Skip pools where dominance calculation fails
                    # (missing balance data, zero total, etc.)
                    continue
            pool_infos = tuple(infos)
            if not pool_infos:
                alerts.append("LIQUIDITY_DATA_UNAVAILABLE")

        observations.append(
            AssetObservation(
                timestamp=timestamp,
                asset=asset,
                price=prices[asset],
                peg_deviation_percent=peg_dev,
                oracle_price=oracle_price,
                oracle_spread_percent=oracle_spread,
                is_yield_bearing=is_yield,
                pools=pool_infos,
                active_alerts=";".join(alerts) or "NONE",
            )
        )
    return observations


# ---------------------------------------------------------------------------
# CSV logging (Upgrade #1: pool name + TVL columns added)
# ---------------------------------------------------------------------------
def append_log(observations: list[AssetObservation]) -> None:
    fieldnames = [
        "Timestamp",
        "Asset",
        "Price",
        "Peg Deviation",
        "Oracle Price",
        "Oracle Spread",
        "Pool Name",
        "Pool TVL (USD)",
        "Pool Dominance",
        "Active Alerts",
    ]
    file_exists = LOG_PATH.exists() and LOG_PATH.stat().st_size > 0
    with LOG_PATH.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for obs in observations:
            peg_str = _format_peg_dev(obs)
            if not obs.pools:
                # No pools found -- write a single row
                writer.writerow(
                    {
                        "Timestamp": obs.timestamp,
                        "Asset": obs.asset,
                        "Price": f"{obs.price:.8f}",
                        "Peg Deviation": peg_str,
                        "Oracle Price": (
                            f"{obs.oracle_price:.8f}"
                            if obs.oracle_price is not None
                            else "N/A"
                        ),
                        "Oracle Spread": (
                            f"{obs.oracle_spread_percent:.4f}%"
                            if obs.oracle_spread_percent is not None
                            else "N/A"
                        ),
                        "Pool Name": "N/A",
                        "Pool TVL (USD)": "N/A",
                        "Pool Dominance": "N/A",
                        "Active Alerts": obs.active_alerts,
                    }
                )
            else:
                # One row per pool
                for pool in obs.pools:
                    writer.writerow(
                        {
                            "Timestamp": obs.timestamp,
                            "Asset": obs.asset,
                            "Price": f"{obs.price:.8f}",
                            "Peg Deviation": peg_str,
                            "Oracle Price": (
                                f"{obs.oracle_price:.8f}"
                                if obs.oracle_price is not None
                                else "N/A"
                            ),
                            "Oracle Spread": (
                                f"{obs.oracle_spread_percent:.4f}%"
                                if obs.oracle_spread_percent is not None
                                else "N/A"
                            ),
                            "Pool Name": pool.name,
                            "Pool TVL (USD)": f"{pool.tvl_usd:.2f}",
                            "Pool Dominance": f"{pool.dominance_percent:.4f}%",
                            "Active Alerts": obs.active_alerts,
                        }
                    )


# ---------------------------------------------------------------------------
# Console report (Upgrades #1, #2, #4 -- two-section display)
# ---------------------------------------------------------------------------
def print_report(observations: list[AssetObservation]) -> None:
    timestamp = observations[0].timestamp if observations else "N/A"

    print("\nAUTOMATED STABLECOIN PEG & POOL MONITOR  (v2.0)")
    print(f"Snapshot: {timestamp}")
    print("=" * 100)

    # Section 1: Price & Peg Status (one row per asset)
    print(
        f"\n  {'Asset':<8} {'Price':<13} {'Peg Deviation':<26} "
        f"{'Oracle Price':<15} {'Spread':<12} {'Alerts'}"
    )
    print(
        f"  {'------':<8} {'----------':<13} {'-------------':<26} "
        f"{'------------':<15} {'------':<12} {'------'}"
    )
    for obs in observations:
        peg_str = _format_peg_dev(obs)
        oracle_price = (
            f"${obs.oracle_price:.6f}"
            if obs.oracle_price is not None
            else "N/A"
        )
        oracle_spread = (
            f"{obs.oracle_spread_percent:.4f}%"
            if obs.oracle_spread_percent is not None
            else "N/A"
        )
        print(
            f"  {obs.asset:<8} ${obs.price:<12.6f} {peg_str:<26} "
            f"{oracle_price:<15} {oracle_spread:<12} {obs.active_alerts}"
        )

    # Section 2: Pool Breakdown (multiple rows per asset)
    print(
        f"\n  Top {TOP_POOLS_PER_ASSET} Curve Pools per Asset (by TVL):"
    )
    print(f"  {'-' * 94}")
    print(
        f"  {'Asset':<8} {'Pool':<38} {'TVL':<14} "
        f"{'Dominance':<12} {'Status'}"
    )
    print(
        f"  {'------':<8} {'----':<38} {'---':<14} "
        f"{'--------':<12} {'------'}"
    )

    for obs in observations:
        if not obs.pools:
            print(
                f"  {obs.asset:<8} {'-- No Curve pool found --':<38}"
            )
            continue
        for i, pool in enumerate(obs.pools):
            asset_label = obs.asset if i == 0 else ""
            # Truncate long pool names for console display
            pool_name = (
                pool.name[:36] if len(pool.name) > 36 else pool.name
            )
            tvl_str = _format_tvl(pool.tvl_usd)
            dom_str = f"{pool.dominance_percent:.2f}%"
            status = "IMBALANCED (!)" if pool.dominance_alert else "OK"
            print(
                f"  {asset_label:<8} {pool_name:<38} {tvl_str:<14} "
                f"{dom_str:<12} {status}"
            )

    print("=" * 100)
    print(f"CSV log appended to: {LOG_PATH}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": "stablecoin-peg-pool-monitor/3.0"})
    timestamp = datetime.now(timezone.utc).isoformat()

    prices = fetch_prices(session)
    web3 = connect_to_ethereum()
    oracle_prices = fetch_oracle_prices(web3)
    pools = fetch_curve_pools(session)
    top_pools = select_top_pools(pools)
    observations = build_observations(
        prices,
        oracle_prices,
        top_pools,
        timestamp,
    )
    append_log(observations)
    print_report(observations)


if __name__ == "__main__":
    main()
