#!/usr/bin/env python3
"""Plot all 9 trials per (benchmark, diversification period) on a single graph.

Produces one PNG per (benchmark, dp) combination, stitching phase1+phase2 for
each trial. Output layout:

    plots/<benchmark>/<benchmark>_dp<N>_all_trials.png

Usage:
    python3 plot_trials.py                  # plot everything
    python3 plot_trials.py --benchmark harfbuzz
    python3 plot_trials.py --dp 2 6
    python3 plot_trials.py --skip-minutes 15
"""

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
TRIALS_DIR = ROOT / "trials"
PLOTS_DIR = ROOT / "plots"

DP_PERIODS = [2, 6, 24]
NUM_TRIALS = 9

USERSTATS_RE = re.compile(
    r"\[(?:UserStats|Client Heartbeat) #0\] run time: (\d+)h-(\d+)m-(\d+)s,.*?"
    r"corpus: (\d+),.*?"
    r"executions: ([\d,]+),.*?"
    r"edges: (\d+)/(\d+)"
)
DATA_RE = re.compile(r"data: (\d+)/(\d+)")


def parse_log(path):
    hours, edges, data, corpus, execs = [], [], [], [], []
    edge_total = 0
    with open(path) as f:
        for line in f:
            m = USERSTATS_RE.search(line)
            if not m:
                continue
            h, mn, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
            t = h + mn / 60 + s / 3600
            hours.append(t)
            corpus.append(int(m.group(4)))
            execs.append(int(m.group(5).replace(",", "")))
            edges.append(int(m.group(6)))
            edge_total = int(m.group(7))
            dm = DATA_RE.search(line)
            data.append(int(dm.group(1)) if dm else None)
    return {
        "hours": hours, "edges": edges, "data": data,
        "corpus": corpus, "execs": execs, "edge_total": edge_total,
    }


def stitch_phases(p1, p2):
    """Stitch phase1 + phase2; drop the early phase2 dip below phase1's final edges."""
    merged = {"hours": [], "edges": [], "data": [], "corpus": [], "execs": []}
    for j in range(len(p1["hours"])):
        merged["hours"].append(p1["hours"][j])
        merged["edges"].append(p1["edges"][j])
        merged["data"].append(p1["data"][j])
        merged["corpus"].append(p1["corpus"][j])
        merged["execs"].append(p1["execs"][j])

    if not p1["hours"]:
        return merged, None

    offset = p1["hours"][-1]
    prev_edges = p1["edges"][-1]
    boundary = offset

    for j in range(len(p2["hours"])):
        if p2["edges"][j] < prev_edges:
            continue  # skip corpus re-import dip
        merged["hours"].append(p2["hours"][j] + offset)
        merged["edges"].append(p2["edges"][j])
        merged["data"].append(p2["data"][j])
        merged["corpus"].append(p2["corpus"][j])
        merged["execs"].append(p2["execs"][j])

    return merged, boundary


def load_trial(trial_dir):
    p1_path = trial_dir / "phase1.log"
    p2_path = trial_dir / "phase2.log"
    if not p1_path.exists() or not p2_path.exists():
        return None, None
    p1 = parse_log(p1_path)
    p2 = parse_log(p2_path)
    if not p1["hours"]:
        return None, None
    return stitch_phases(p1, p2)


def plot_dp_group(benchmark, dp, trials, skip_minutes, metric, out_path):
    skip_hours = skip_minutes / 60
    fig, ax = plt.subplots(figsize=(11, 6))
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    boundary_times = []
    for i, (label, data, boundary) in enumerate(trials):
        idx = [j for j, t in enumerate(data["hours"]) if t >= skip_hours]
        if not idx:
            continue
        h = [data["hours"][j] for j in idx]
        if metric == "edges":
            v = [data["edges"][j] for j in idx]
        elif metric == "data":
            v = [data["data"][j] if data["data"][j] is not None else 0 for j in idx]
        elif metric == "corpus":
            v = [data["corpus"][j] for j in idx]
        ax.plot(h, v, label=label, color=colors[i % len(colors)], linewidth=1.3, alpha=0.85)
        if boundary is not None:
            boundary_times.append(boundary)

    if boundary_times:
        avg_boundary = sum(boundary_times) / len(boundary_times)
        if avg_boundary >= skip_hours:
            ax.axvline(x=avg_boundary, color="gray", linestyle="--", alpha=0.6)
            ax.text(avg_boundary, ax.get_ylim()[1], " phase1->phase2",
                    va="top", ha="left", fontsize=8, color="gray")

    ylabel = {"edges": "Edges Hit", "data": "Data Buckets Hit", "corpus": "Corpus Size"}[metric]
    title_metric = {"edges": "Edge Coverage", "data": "Data Coverage", "corpus": "Corpus Growth"}[metric]
    ax.set_xlabel("Time (hours)")
    ax.set_ylabel(ylabel)
    ax.set_title(f"{benchmark} — {title_metric} — diversification {dp}h + libafl 12h "
                 f"(after {skip_minutes:.0f}min)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right", fontsize=9, ncol=2)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Saved {out_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--benchmark", nargs="*",
                    help="Limit to specific benchmark dirs (default: all under trials/)")
    ap.add_argument("--dp", nargs="*", type=int,
                    help="Limit to specific dp periods (default: 2 6 24)")
    ap.add_argument("--skip-minutes", type=float, default=10,
                    help="Minutes to clip from the start (default: 10)")
    ap.add_argument("--metric", choices=["edges", "data", "corpus"], default="edges",
                    help="Which metric to plot (default: edges)")
    args = ap.parse_args()

    benchmarks = args.benchmark or sorted(p.name for p in TRIALS_DIR.iterdir() if p.is_dir())
    dps = args.dp or DP_PERIODS

    for bench in benchmarks:
        bench_dir = TRIALS_DIR / bench
        if not bench_dir.is_dir():
            print(f"Skipping {bench}: not a directory")
            continue
        for dp in dps:
            trials = []
            for n in range(1, NUM_TRIALS + 1):
                tdir = bench_dir / f"dp{dp}_trial{n}"
                if not tdir.is_dir():
                    print(f"  Missing: {tdir}")
                    continue
                merged, boundary = load_trial(tdir)
                if merged is None:
                    print(f"  No data: {tdir}")
                    continue
                trials.append((f"trial{n}", merged, boundary))
            if not trials:
                print(f"No trials found for {bench} dp{dp}")
                continue
            out_path = PLOTS_DIR / bench / f"{bench}_dp{dp}_all_trials_{args.metric}.png"
            plot_dp_group(bench, dp, trials, args.skip_minutes, args.metric, out_path)


if __name__ == "__main__":
    main()
