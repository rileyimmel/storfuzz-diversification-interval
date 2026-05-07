#!/usr/bin/env python3
"""Plot coverage growth from StorFuzz/LibAFL log files.

Produces two PNGs per run: a full plot and a zoomed plot (skipping initial burst).

Usage:
    # Single phase
    python3 scripts/plot_coverage.py trials/harfbuzz/dp24_trial1/phase1.log

    # Both phases stitched into one continuous timeline
    python3 scripts/plot_coverage.py --stitch \\
        trials/harfbuzz/dp2_trial1/phase1.log \\
        trials/harfbuzz/dp2_trial1/phase2.log

    # Overlay multiple logs (separate lines, no time stitching)
    python3 scripts/plot_coverage.py \\
        trials/harfbuzz/dp2_trial1/phase1.log \\
        trials/harfbuzz/dp2_trial2/phase1.log \\
        --labels "Trial 1" "Trial 2"

    # Custom output path
    python3 scripts/plot_coverage.py phase1.log -o my_plot.png

    # Adjust zoomed plot cutoff (default: 10 min)
    python3 scripts/plot_coverage.py phase1.log --skip-minutes 20
"""

import argparse
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt

USERSTATS_RE = re.compile(
    r"\[UserStats #0\] run time: (\d+)h-(\d+)m-(\d+)s,.*?"
    r"corpus: (\d+),.*?"
    r"executions: ([\d,]+),.*?"
    r"edges: (\d+)/(\d+)"
)

DATA_RE = re.compile(r"data: (\d+)/(\d+)")


def parse_log(path):
    hours, edges_list, data_list, corpus_list, execs_list = [], [], [], [], []
    edge_total = 0
    for line in open(path):
        m = USERSTATS_RE.search(line)
        if not m:
            continue
        h, mn, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        t = h + mn / 60 + s / 3600
        corpus = int(m.group(4))
        execs = int(m.group(5).replace(",", ""))
        edge_hit, edge_total = int(m.group(6)), int(m.group(7))

        dm = DATA_RE.search(line)
        data_hit = int(dm.group(1)) if dm else None

        hours.append(t)
        edges_list.append(edge_hit)
        data_list.append(data_hit)
        corpus_list.append(corpus)
        execs_list.append(execs)

    return {
        "hours": hours,
        "edges": edges_list,
        "data": data_list,
        "corpus": corpus_list,
        "execs": execs_list,
        "edge_total": edge_total,
    }


def stitch_datasets(datasets, labels):
    """Merge multiple sequential datasets into one continuous timeline.

    For phases after the first, skip early points where edge coverage is below
    the previous phase's final value (the corpus re-import dip).
    """
    merged = {"hours": [], "edges": [], "data": [], "corpus": [], "execs": [], "edge_total": 0}
    offset = 0.0
    boundaries = []  # (time, label) for vertical lines
    prev_edges = 0

    for i, d in enumerate(datasets):
        if not d["hours"]:
            continue
        if i > 0:
            boundaries.append((offset, labels[i]))
        for j in range(len(d["hours"])):
            # Skip re-import dip in subsequent phases
            if i > 0 and d["edges"][j] < prev_edges:
                continue
            merged["hours"].append(d["hours"][j] + offset)
            merged["edges"].append(d["edges"][j])
            merged["data"].append(d["data"][j])
            merged["corpus"].append(d["corpus"][j])
            merged["execs"].append(d["execs"][j])
        if merged["edges"]:
            prev_edges = merged["edges"][-1]
        offset = merged["hours"][-1]
        merged["edge_total"] = max(merged["edge_total"], d["edge_total"])

    return merged, boundaries


def make_plots(datasets, labels, has_data, output, title_suffix="",
               skip_minutes=0, boundaries=None, edges_only=False):
    """Generate a single figure with edge, data, and corpus subplots."""
    if edges_only:
        panels = ["edges"]
    else:
        panels = ["edges"] + (["data"] if has_data else []) + ["corpus"]
    nplots = len(panels)

    fig, axes = plt.subplots(nplots, 1, figsize=(10, 4 * nplots), sharex=True)
    if nplots == 1:
        axes = [axes]

    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    skip_hours = skip_minutes / 60

    for i, (d, label) in enumerate(zip(datasets, labels)):
        c = colors[i % len(colors)]

        # Filter to points after skip threshold
        idx = [j for j, t in enumerate(d["hours"]) if t >= skip_hours]
        if not idx:
            continue
        h = [d["hours"][j] for j in idx]

        for ax_idx, panel in enumerate(panels):
            if panel == "edges":
                vals = [d["edges"][j] for j in idx]
                axes[ax_idx].set_ylabel("Edges Hit")
                axes[ax_idx].set_title("Edge Coverage" + title_suffix)
            elif panel == "data":
                vals = [d["data"][j] if d["data"][j] is not None else 0 for j in idx]
                axes[ax_idx].set_ylabel("Data Buckets Hit")
                axes[ax_idx].set_title("Data Coverage" + title_suffix)
            elif panel == "corpus":
                vals = [d["corpus"][j] for j in idx]
                axes[ax_idx].set_ylabel("Corpus Size")
                axes[ax_idx].set_title("Corpus Growth" + title_suffix)
            axes[ax_idx].plot(h, vals, label=label, color=c, linewidth=1.5)

    # Draw vertical lines at phase boundaries
    if boundaries:
        for btime, blabel in boundaries:
            if btime < skip_hours:
                continue
            for ax in axes:
                ax.axvline(x=btime, color="gray", linestyle="--", alpha=0.7)
                ax.text(btime, ax.get_ylim()[1], f" {blabel}",
                        va="top", ha="left", fontsize=8, color="gray")

    for ax in axes:
        ax.legend()
        ax.grid(True, alpha=0.3)
    axes[-1].set_xlabel("Time (hours)")

    fig.tight_layout()
    fig.savefig(output, dpi=150)
    print(f"Saved to {output}")
    plt.close(fig)


PLOTS_DIR = Path(__file__).resolve().parent.parent / "plots"

# Regex to extract dp hours from trial dir name like "dp24_trial1"
DP_RE = re.compile(r"dp(\d+)_trial")


def auto_output_dir(log_path):
    """Derive output directory from log path structure.

    Given a path like trials/harfbuzz/dp24_trial1/phase1.log, returns:
      plots/harfbuzz/harf24/
    """
    log_path = Path(log_path).resolve()
    trial_dir_name = log_path.parent.name        # e.g. "dp24_trial1"
    benchmark = log_path.parent.parent.name       # e.g. "harfbuzz"

    m = DP_RE.search(trial_dir_name)
    dp_hours = m.group(1) if m else "unknown"
    # Shorten benchmark for subfolder: "harfbuzz" -> "harf", "openthread" -> "open", etc.
    short = benchmark[:4]
    subfolder = f"{short}{dp_hours}"              # e.g. "harf24"

    out_dir = PLOTS_DIR / benchmark / subfolder
    return out_dir


def auto_output_name(args):
    """Derive output name and directory from log path(s)."""
    log_path = Path(args.logs[0]).resolve()
    trial_dir_name = log_path.parent.name  # e.g. "dp24_trial1"

    parent = auto_output_dir(args.logs[0])

    if args.stitch:
        stem = f"{trial_dir_name}_stitched_coverage"
    else:
        log_stem = log_path.stem  # e.g. "phase1"
        stem = f"{trial_dir_name}_{log_stem}_coverage"
    return stem, ".png", parent


EXAMPLES = """
examples:
  # Plot a single log file
  python3 scripts/plot_coverage.py trials/harfbuzz/dp24_trial1/phase1.log

  # Stitch phase 1 + phase 2 into one continuous timeline
  python3 scripts/plot_coverage.py --stitch \\
      trials/harfbuzz/dp2_trial1/phase1.log \\
      trials/harfbuzz/dp2_trial1/phase2.log

  # Overlay multiple trials (separate lines on same plot)
  python3 scripts/plot_coverage.py \\
      trials/harfbuzz/dp2_trial1/phase1.log \\
      trials/harfbuzz/dp2_trial2/phase1.log \\
      --labels "Trial 1" "Trial 2"

  # Save to a specific file and adjust zoom cutoff
  python3 scripts/plot_coverage.py phase1.log -o my_plot.png --skip-minutes 20
"""


def main():
    ap = argparse.ArgumentParser(
        description="Plot coverage growth from StorFuzz/LibAFL log files.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("logs", nargs="*", help="Log file(s) to plot")
    ap.add_argument("--labels", nargs="*", help="Labels for each log file")
    ap.add_argument("-o", "--output", help="Output filename (auto-generated if omitted)")
    ap.add_argument(
        "--skip-minutes", type=float, default=10,
        help="Minutes to skip for the zoomed plot (default: 10)",
    )
    ap.add_argument(
        "--stitch", action="store_true",
        help="Stitch logs into one continuous timeline (e.g. phase1 + phase2)",
    )
    ap.add_argument(
        "--edges-only", action="store_true",
        help="Only plot edge (code branch) coverage, skip data and corpus graphs",
    )
    args = ap.parse_args()

    if not args.logs:
        ap.print_help()
        sys.exit(0)

    labels = args.labels or [Path(p).stem for p in args.logs]
    if len(labels) < len(args.logs):
        labels.extend(Path(p).stem for p in args.logs[len(labels):])

    datasets = []
    for path in args.logs:
        d = parse_log(path)
        if not d["hours"]:
            print(f"Warning: no UserStats lines found in {path}", file=sys.stderr)
            continue
        datasets.append(d)

    if not datasets:
        sys.exit("No data found in any log file.")

    boundaries = None
    if args.stitch:
        merged, boundaries = stitch_datasets(datasets, labels)
        datasets = [merged]
        labels = ["stitched"]

    has_data = any(any(v is not None for v in d["data"]) for d in datasets)

    if args.output:
        stem = Path(args.output).stem
        suffix = Path(args.output).suffix or ".png"
        parent = Path(args.output).parent
    else:
        stem, suffix, parent = auto_output_name(args)

    parent.mkdir(parents=True, exist_ok=True)

    eo = args.edges_only

    # Full plot
    make_plots(datasets, labels, has_data, str(parent / f"{stem}{suffix}"),
               boundaries=boundaries, edges_only=eo)

    # Zoomed plot (skip initial burst)
    skip = args.skip_minutes
    zoomed_stem = stem.replace("_coverage", "") + "_coverage_zoomed"
    make_plots(
        datasets, labels, has_data, str(parent / f"{zoomed_stem}{suffix}"),
        title_suffix=f" (after {skip:.0f}min)", skip_minutes=skip,
        boundaries=boundaries, edges_only=eo,
    )


if __name__ == "__main__":
    main()
