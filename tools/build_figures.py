"""Rebuild source-attributed repository figures from committed compact inputs."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs/data"
ASSETS = ROOT / "docs/assets"
PALETTE = ["#067f79", "#d17b23", "#5555ac", "#1974b8", "#bd4f68", "#5b8d36"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def read(name):
    with (DATA / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def save(fig, name):
    ASSETS.mkdir(exist_ok=True)
    for extension in ["svg", "png"]:
        path = ASSETS / f"{name}.{extension}"
        fig.savefig(path, dpi=160, facecolor="white", bbox_inches="tight")
        if extension == "svg":
            path.write_text(
                "\n".join(line.rstrip() for line in path.read_text(encoding="utf-8").splitlines()) + "\n",
                encoding="utf-8",
                newline="\n",
            )
    plt.close(fig)


def main():
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.labelcolor": "#334155",
            "text.color": "#12263b",
            "axes.titleweight": "bold",
            "svg.fonttype": "none",
        }
    )
    rows = read("continents_2024_monthly.csv")
    cities = list(dict.fromkeys(r["city"] for r in rows))
    assert len(cities) == 6 and len(rows) == 72
    fig, ax = plt.subplots(figsize=(12, 6.1))
    for color, city in zip(PALETTE, cities):
        subset = [r for r in rows if r["city"] == city]
        assert [int(r["month"]) for r in subset] == list(range(1, 13))
        ax.plot(
            range(12),
            [float(r["mean_temperature_c"]) for r in subset],
            color=color,
            lw=2.5,
            marker="o",
            ms=4,
            label=f"{city} · {subset[0]['continent']}",
        )
    ax.set(
        title="One actual year. Six cities. Six continents.",
        ylabel="Monthly mean dry-bulb temperature (°C)",
        xticks=range(12),
        xticklabels=MONTHS,
        xlim=(-0.2, 11.2),
    )
    ax.grid(axis="y", alpha=0.2)
    ax.legend(ncol=3, fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.12), frameon=False)
    fig.text(
        0.02,
        -0.13,
        "2024 · 8,784 hourly records per city · ERA5 via Open-Meteo / Copernicus C3S; locations: GeoNames\n"
        "Generated with pyEPW 0.4.1; fixed local standard time. Model profiles, not local thermometer observations.",
        fontsize=9,
        color="#475569",
    )
    save(fig, "continents_temperature")

    matrix = np.array([[float(r["mean_daily_ghi_kwh_m2"]) for r in rows if r["city"] == c] for c in cities])
    fig, ax = plt.subplots(figsize=(12, 4.7))
    im = ax.imshow(matrix, cmap="YlGnBu", aspect="auto", vmin=0, vmax=max(8, matrix.max()))
    for y in range(6):
        for x in range(12):
            ax.text(
                x,
                y,
                f"{matrix[y, x]:.1f}",
                ha="center",
                va="center",
                fontsize=10,
                color="white" if matrix[y, x] > 6 else "#12263b",
            )
    ax.set(
        title="Surface solar energy follows different seasonal cycles",
        yticks=range(6),
        yticklabels=cities,
        xticks=range(12),
        xticklabels=MONTHS,
    )
    fig.colorbar(im, ax=ax, pad=0.02, label="Mean daily GHI (kWh/m²/day)")
    fig.text(
        0.02,
        -0.03,
        "Actual year 2024 · Hourly GHI summed, divided by days in month, converted from Wh to kWh.\n"
        "Source: ERA5 via Open-Meteo / Copernicus C3S (CC BY 4.0); city locations: GeoNames. No local radiation validation implied.",
        fontsize=9,
        color="#475569",
    )
    save(fig, "continents_solar")

    bench = read("benchmark_v0_2_city_summary.csv")
    names = [r["city"].replace("Frankfurt am Main", "Frankfurt").replace("New York City", "New York") for r in bench]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5), gridspec_kw={"width_ratios": [1, 1.25]}, sharey=True)
    y = np.arange(len(bench))
    temperature = [float(r["temperature_mae_c"]) for r in bench]
    wind = [float(r["wind_bias_percent"]) for r in bench]
    axes[0].barh(y, temperature, color="#087f79", height=0.65)
    axes[0].set(yticks=y, yticklabels=names, xlabel="Hourly temperature MAE (°C)", xlim=(0, 2.1))
    axes[0].invert_yaxis()
    axes[1].barh(y, wind, color=["#c46a43" if v < 0 else "#447db5" for v in wind], height=0.65)
    axes[1].axvline(0, color="#475569", lw=1)
    axes[1].set(xlabel="Difference of matched mean wind speed (%)", xlim=(-58, 10))
    for i, (t, w) in enumerate(zip(temperature, wind)):
        axes[0].text(t + 0.03, i, f"{t:.2f}", va="center", fontsize=9)
        axes[1].text(
            w - 1 if w < 0 else w + 1, i, f"{w:+.1f}", va="center", ha="right" if w < 0 else "left", fontsize=9
        )
    for ax in axes:
        ax.grid(axis="x", alpha=0.16)
        ax.set_axisbelow(True)
    fig.suptitle("Conversion can pass while weather agreement varies", fontsize=16, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.text(
        0.02,
        -0.06,
        "Historical version 0.2.0 snapshot · 2005–2024 · 10 cities / 200 actual years\n"
        "ERA5 via Open-Meteo versus nearby station observations (NOAA NCEI and originating networks). Spatial/timing differences apply.\n"
        "Not a new validation of 0.4.1 supplements. Source summaries and study limitations are committed in docs/data and docs/validation_v0_2.md.",
        fontsize=9,
        color="#475569",
    )
    save(fig, "benchmark_v0_2")
    print("Built three attributed figures in SVG and PNG.")


if __name__ == "__main__":
    main()
