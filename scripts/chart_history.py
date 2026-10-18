"""Plot historical USDe oracle spread and Curve pool dominance."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT_ROOT / "peg_monitor_log.csv"
OUTPUT_PATH = PROJECT_ROOT / "usde_risk_chart.png"
FIGURE_BACKGROUND = "#0e1117"
ORACLE_COLOR = "#FF5252"
DOMINANCE_COLOR = "#00E5FF"


def load_usde_history(csv_path: Path) -> pd.DataFrame:
    """Load, clean, and select the USDe pool history from the monitor log."""
    data = pd.read_csv(csv_path)

    required_columns = {
        "Asset",
        "Oracle Spread",
        "Pool Dominance",
        "Pool Name",
    }
    missing_columns = required_columns.difference(data.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"CSV is missing required columns: {missing}.")

    for column in ("Oracle Spread", "Pool Dominance"):
        data[column] = pd.to_numeric(
            data[column].astype("string").str.replace("%", "", regex=False),
            errors="coerce",
        )

    data = data.dropna(subset=["Oracle Spread", "Pool Dominance"])
    usde_data = data[data["Asset"] == "USDe"].copy()
    if usde_data.empty:
        return usde_data

    preferred_pool = usde_data[usde_data["Pool Name"] == "USDe-USDC"]
    if not preferred_pool.empty:
        selected_pool = "USDe-USDC"
    else:
        selected_pool = usde_data["Pool Name"].value_counts().idxmax()

    return (
        usde_data[usde_data["Pool Name"] == selected_pool]
        .reset_index(drop=True)
    )


def plot_usde_history(data: pd.DataFrame, output_path: Path) -> None:
    """Create and save the dual-axis USDe risk chart."""
    plt.style.use("dark_background")
    fig, ax1 = plt.subplots(figsize=(12, 6), facecolor=FIGURE_BACKGROUND)
    ax2 = ax1.twinx()
    ax1.set_facecolor(FIGURE_BACKGROUND)
    ax2.set_facecolor("none")

    sparse_data = len(data) <= 3
    marker_size = 60 if sparse_data else 28
    x_values = range(1, len(data) + 1)

    spread_line = ax1.plot(
        x_values,
        data["Oracle Spread"],
        color=ORACLE_COLOR,
        linewidth=2.0,
        label="Oracle Spread (%)",
    )[0]

    ax1.fill_between(
        x_values,
        data["Oracle Spread"],
        0,
        color=ORACLE_COLOR,
        alpha=0.08,
    )
    ax1.scatter(
        x_values,
        data["Oracle Spread"],
        color=ORACLE_COLOR,
        edgecolors=FIGURE_BACKGROUND,
        linewidths=0.8,
        s=marker_size,
        alpha=0.9,
        zorder=3,
    )
    ax1.axhline(
        0.5,
        color=ORACLE_COLOR,
        linestyle="--",
        linewidth=1.0,
        alpha=0.45,
    )

    dominance_line = ax2.plot(
        x_values,
        data["Pool Dominance"],
        color=DOMINANCE_COLOR,
        linewidth=2.0,
        label="Pool Dominance (%)",
    )[0]
    ax2.scatter(
        x_values,
        data["Pool Dominance"],
        color=DOMINANCE_COLOR,
        edgecolors=FIGURE_BACKGROUND,
        linewidths=0.8,
        s=marker_size,
        alpha=0.9,
        zorder=3,
    )
    ax2.axhline(
        75.0,
        color=DOMINANCE_COLOR,
        linestyle="--",
        linewidth=1.0,
        alpha=0.45,
    )

    pool_name = str(data["Pool Name"].iloc[0])
    ax1.set_title(
        "USDe Risk Chart | Oracle Latency Spread vs. Curve Dominance\n"
        f"Active pool: {pool_name}",
        loc="left",
        fontsize=15,
        fontweight="bold",
        pad=14,
    )
    ax1.set_xlabel("Observation")
    ax1.set_ylabel("Oracle Spread (%)", color=ORACLE_COLOR)
    ax2.set_ylabel("Pool Dominance (%)", color=DOMINANCE_COLOR)
    ax1.tick_params(axis="y", labelcolor=ORACLE_COLOR)
    ax2.tick_params(axis="y", labelcolor=DOMINANCE_COLOR)
    ax1.grid(True, linestyle=":", color="#ffffff", alpha=0.15)
    ax2.grid(False)

    ax1.text(
        0.99,
        0.5,
        "Oracle threshold 0.5%",
        transform=ax1.get_yaxis_transform(),
        color=ORACLE_COLOR,
        fontsize=9,
        ha="right",
        va="bottom",
        alpha=0.85,
    )
    ax2.text(
        0.99,
        75.0,
        "Pool threshold 75%",
        transform=ax2.get_yaxis_transform(),
        color=DOMINANCE_COLOR,
        fontsize=9,
        ha="right",
        va="bottom",
        alpha=0.85,
    )

    legend = ax1.legend(
        handles=[spread_line, dominance_line],
        loc="upper right",
        frameon=True,
        facecolor="#18202b",
        edgecolor="#536170",
        framealpha=0.8,
    )
    for text in legend.get_texts():
        text.set_color("#f5f7fa")

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def main() -> None:
    """Generate the historical USDe risk chart when sufficient data exists."""
    if not CSV_PATH.exists():
        print(f"Log file not found: {CSV_PATH}")
        print("More logged snapshots are needed before a chart can be generated.")
        return

    try:
        history = load_usde_history(CSV_PATH)
    except (OSError, pd.errors.ParserError, ValueError) as exc:
        print(f"Could not load valid telemetry data: {exc}")
        return

    if history.empty:
        print("No valid USDe telemetry rows were found.")
        print("More logged snapshots are needed before a chart can be generated.")
        return

    plot_usde_history(history, OUTPUT_PATH)
    print(f"Saved USDe risk chart to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
