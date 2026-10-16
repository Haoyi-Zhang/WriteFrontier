"""Render the retained reserve/epoch and finite slack curves as native-font vector PDFs.

Inputs are existing results/frontier CSVs. This optional figure authoring step
uses direct Matplotlib PDF rendering; it does not run the scientific campaigns.
"""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal
from pathlib import Path


N, QUANTUM, COMMIT, PATTERNS = 128, 32, 1, 5184
COLUMN_WIDTH_TEX_PT = 430.00462  # Current single-column manuscript log.
HEIGHT_IN = 2.45
TEX_PT_TO_BP = 72.0 / 72.27


def reviewed_points(data_dir):
    """Read only the two retained chart inputs; no optimizer or data regeneration."""
    with (data_dir / "unit-exchange-frontier.csv").open(newline="", encoding="utf-8-sig") as handle:
        rows = [r for r in csv.DictReader(handle) if int(r["segments_per_tier"]) == N]
    if any(int(r["quantum"]) != QUANTUM or int(r["commit_bytes"]) != COMMIT for r in rows):
        raise ValueError("The chart requires the declared quantum and commit charge")
    unit = tuple(sorted((int(r["reserve_each_tier"]), int(r["exact_batches"])) for r in rows))
    if tuple(r for r, _ in unit) != tuple(range(1, 17)):
        raise ValueError("The retained per-tier reserve domain must be 1 through 16")
    if any(epochs != (N + r - 1) // r + 1 for r, epochs in unit):
        raise ValueError("The retained epoch counts disagree with the displayed formula")
    with (data_dir / "slack-curve.csv").open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if any(int(r["patterns"]) != PATTERNS for r in rows):
        raise ValueError("The slack curve requires the declared pattern denominator")
    slack = tuple(sorted((int(r["extra_total_reserve_units"]),
                          Decimal(r["lower_bound_fraction"]) * Decimal(100)) for r in rows))
    if tuple(x for x, _ in slack) != tuple(range(7)):
        raise ValueError("The retained slack domain must be 0 through 6")
    if any(not Decimal(0) <= y <= Decimal(100) for _, y in slack):
        raise ValueError("A retained percentage is outside the declared range")
    return unit, slack


def render(column_width_tex_pt, data_dir, output):
    if column_width_tex_pt <= 0:
        raise ValueError("Column width must be positive")

    # Check Matplotlib availability before creating authoring directories.
    import importlib.util
    if importlib.util.find_spec("matplotlib") is None:
        raise RuntimeError("Matplotlib is required; no automatic installation")

    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    names = ("unit-frontier.pdf", "slack-curve.pdf")

    import matplotlib as mpl
    mpl.use("Agg")
    import matplotlib.pyplot as plt

    # Embedded STIX text and math; TeX is not called by this plotting path.
    rc = {
        "font.family": "STIXGeneral",
        "mathtext.fontset": "stix",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "font.size": 9.0,
        "text.usetex": False,
        "axes.labelsize": 8.0,  # small in current 9pt amsart base.
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "legend.fontsize": 8.5,
        "axes.linewidth": 0.4 * TEX_PT_TO_BP,
        "grid.linewidth": 0.3 * TEX_PT_TO_BP,
        "grid.color": "#d9d9d9",  # black!15
        "grid.linestyle": "-",
        "axes.formatter.use_mathtext": False,
        "axes.unicode_minus": False,
        "savefig.bbox": None,
    }
    width_bp = column_width_tex_pt * TEX_PT_TO_BP
    height_bp = HEIGHT_IN * 72.0
    left, right, bottom, top = 48.0, 10.0, 32.0, 22.0
    if width_bp <= left + right + 100:
        raise ValueError("Column too narrow for the fixed plot margins")
    rect = (
        left / width_bp, bottom / height_bp,
        (width_bp - left - right) / width_bp,
        (height_bp - bottom - top) / height_bp,
    )
    unit, slack = reviewed_points(data_dir)

    def base_axes():
        fig = plt.figure(figsize=(width_bp / 72.0, HEIGHT_IN))
        ax = fig.add_axes(rect)
        ax.set_xscale("linear")
        ax.set_yscale("linear")
        ax.set_axisbelow(True)
        ax.grid(True, which="major")
        ax.minorticks_off()
        ax.tick_params(
            axis="both", which="major", direction="in", top=True, right=True,
            labeltop=False, labelright=False, length=3 * TEX_PT_TO_BP,
            width=0.4 * TEX_PT_TO_BP, pad=3 * TEX_PT_TO_BP,
        )
        return fig, ax

    def series(ax, points, marker, radius_tex_pt, label):
        # Ordinary solid connectors are faithful to the current TikZ source.
        # Do not replace with step(), stairs(), smoothing or dense sampling.
        ax.plot(
            [p[0] for p in points], [float(p[1]) for p in points],
            color="black", linewidth=0.6 * TEX_PT_TO_BP,
            linestyle="-", drawstyle="default", marker=marker,
            markersize=2 * radius_tex_pt * TEX_PT_TO_BP,
            markerfacecolor="#0000cc", markeredgecolor="black",
            markeredgewidth=0.6 * TEX_PT_TO_BP,
            label=label, rasterized=False,
        )

    with mpl.rc_context(rc):
        fig, ax = base_axes()
        series(ax, unit, "o", 1.3, r"exact DP and $\lceil128/r\rceil+1$")
        ax.set_xlim(0.5, 16.5)
        ax.set_ylim(0, 132)
        ticks = (1, 2, 4, 8, 12, 16)
        ax.set_xticks(ticks, [str(x) for x in ticks])
        ticks = (0, 32, 64, 96, 128)
        ax.set_yticks(ticks, [str(y) for y in ticks])
        ax.set_xlabel(r"reserve in each tier $r$", labelpad=5 * TEX_PT_TO_BP)
        ax.set_ylabel("minimum recovery epochs", labelpad=6 * TEX_PT_TO_BP)
        ax.legend(loc="upper right", bbox_to_anchor=(0.98, 0.98),
                  frameon=False, borderaxespad=0, handlelength=2)
        fig.savefig(output / names[0], format="pdf", bbox_inches=None,
                    metadata={"Creator":"Python Matplotlib","CreationDate":None,"ModDate":None})
        plt.close(fig)

        fig, ax = base_axes()
        series(ax, slack, "s", 2.0, "optimal cost equals LB")
        ax.set_xlim(-0.2, 6.2)
        ax.set_ylim(0, 105)
        ticks = tuple(range(7))
        ax.set_xticks(ticks, [str(x) for x in ticks])
        ticks = (0, 20, 40, 60, 80, 100)
        ax.set_yticks(ticks, [str(y) for y in ticks])
        ax.set_xlabel("extra total reserve units", labelpad=5 * TEX_PT_TO_BP)
        ax.set_ylabel("frontier instances at lower bound (%)",
                      labelpad=6 * TEX_PT_TO_BP)
        ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.04),
                  frameon=False, borderaxespad=0, handlelength=2)
        fig.savefig(output / names[1], format="pdf", bbox_inches=None,
                    metadata={"Creator":"Python Matplotlib","CreationDate":None,"ModDate":None})
        plt.close(fig)

    print(f"Vector PDFs written to {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent / "results" / "frontier")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--column-width-tex-pt", type=float, default=COLUMN_WIDTH_TEX_PT)
    args = parser.parse_args()
    render(args.column_width_tex_pt, args.data_dir, args.output_dir)


if __name__ == "__main__":
    main()
