#!/usr/bin/env python3
"""Generate aggregate analysis tables and figures for the StorFuzz trials."""

import argparse
import csv
import math
import os
import re
import statistics
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
TRIALS_DIR = ROOT / "trials"
ANALYSIS_DIR = ROOT / "analysis"
ANALYSIS_PLOTS_DIR = ROOT / "plots" / "analysis"

DP_PERIODS = [2, 6, 24]
NUM_TRIALS = 9
SKIP_MINUTES = 10
RATE_WINDOW_HOURS = 1.0

USERSTATS_RE = re.compile(
    r"\[(?:UserStats|Client Heartbeat) #0\] run time: (\d+)h-(\d+)m-(\d+)s,.*?"
    r"corpus: (\d+),.*?"
    r"executions: ([\d,]+),.*?"
    r"edges: (\d+)/(\d+)"
)
DATA_RE = re.compile(r"data: (\d+)/(\d+)")


def parse_log(path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = USERSTATS_RE.search(line)
            if not m:
                continue
            hours = int(m.group(1)) + int(m.group(2)) / 60 + int(m.group(3)) / 3600
            dm = DATA_RE.search(line)
            rows.append(
                {
                    "hours": hours,
                    "corpus": int(m.group(4)),
                    "execs": int(m.group(5).replace(",", "")),
                    "data": int(dm.group(1)) if dm else None,
                    "edges": int(m.group(6)),
                    "edge_total": int(m.group(7)),
                }
            )
    return rows


def value_at(rows, metric, hours):
    candidates = [r for r in rows if r["hours"] <= hours]
    if candidates:
        value = candidates[-1][metric]
        return 0 if value is None else value
    if not rows:
        return 0
    value = rows[0][metric]
    return 0 if value is None else value


def first_at_or_after(rows, min_hours):
    for row in rows:
        if row["hours"] >= min_hours:
            return row
    return rows[-1] if rows else None


def metric_rate(rows, metric, window_hours):
    if not rows:
        return 0.0
    end = rows[-1]["hours"]
    start = max(0.0, end - window_hours)
    end_value = value_at(rows, metric, end)
    start_value = value_at(rows, metric, start)
    actual_window = max(end - start, 1e-9)
    return (end_value - start_value) / actual_window


def stitch_phases(phase1, phase2):
    merged = []
    merged.extend(dict(r) for r in phase1)
    if not phase1:
        return merged

    offset = phase1[-1]["hours"]
    prev_edges = phase1[-1]["edges"]
    for row in phase2:
        if row["edges"] < prev_edges:
            continue
        shifted = dict(row)
        shifted["hours"] = row["hours"] + offset
        merged.append(shifted)
    return merged


def load_trial(benchmark, dp, trial_num):
    trial_dir = TRIALS_DIR / benchmark / f"dp{dp}_trial{trial_num}"
    p1 = parse_log(trial_dir / "phase1.log")
    p2 = parse_log(trial_dir / "phase2.log")
    return trial_dir, p1, p2, stitch_phases(p1, p2)


def summarize_trial(benchmark, dp, trial_num):
    trial_dir, p1, p2, merged = load_trial(benchmark, dp, trial_num)
    if not p1 or not p2 or not merged:
        raise ValueError(f"missing data for {trial_dir}")

    skip_hours = SKIP_MINUTES / 60
    start = first_at_or_after(p1, skip_hours) or p1[0]
    p1_final = p1[-1]
    p2_final = p2[-1]
    final = merged[-1]
    phase1_hours = p1_final["hours"]
    phase2_hours = p2_final["hours"]
    total_hours = final["hours"]

    phase1_edge_gain = p1_final["edges"] - start["edges"]
    phase2_edge_gain = final["edges"] - p1_final["edges"]
    total_edge_gain = final["edges"] - start["edges"]
    phase1_data_gain = (p1_final["data"] or 0) - (start["data"] or 0)
    phase1_corpus_gain = p1_final["corpus"] - start["corpus"]

    return {
        "benchmark": benchmark,
        "dp_hours": dp,
        "trial": trial_num,
        "phase1_hours": phase1_hours,
        "phase2_hours": phase2_hours,
        "total_hours": total_hours,
        "start_edges_after_10m": start["edges"],
        "phase1_final_edges": p1_final["edges"],
        "final_edges": final["edges"],
        "edges_at_14h": value_at(merged, "edges", 14.0),
        "edge_total": final["edge_total"],
        "phase1_edge_gain": phase1_edge_gain,
        "phase2_edge_gain": phase2_edge_gain,
        "total_edge_gain": total_edge_gain,
        "phase2_edge_gain_per_hour": phase2_edge_gain / max(phase2_hours, 1e-9),
        "total_edge_gain_per_hour": total_edge_gain / max(total_hours - skip_hours, 1e-9),
        "phase1_final_data": p1_final["data"] or 0,
        "phase1_data_gain": phase1_data_gain,
        "phase1_data_gain_per_hour": phase1_data_gain / max(phase1_hours - skip_hours, 1e-9),
        "phase1_data_last_hour_rate": metric_rate(p1, "data", RATE_WINDOW_HOURS),
        "phase1_edge_last_hour_rate": metric_rate(p1, "edges", RATE_WINDOW_HOURS),
        "phase1_final_corpus": p1_final["corpus"],
        "phase1_corpus_gain": phase1_corpus_gain,
        "phase1_corpus_gain_per_hour": phase1_corpus_gain / max(phase1_hours - skip_hours, 1e-9),
        "phase1_corpus_last_hour_rate": metric_rate(p1, "corpus", RATE_WINDOW_HOURS),
        "final_corpus": final["corpus"],
        "final_data": final["data"] or 0,
    }


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def group_stats(rows):
    metrics = [
        "final_edges",
        "phase1_edge_gain",
        "phase2_edge_gain",
        "total_edge_gain",
        "total_edge_gain_per_hour",
        "edges_at_14h",
        "phase1_data_last_hour_rate",
        "phase1_corpus_last_hour_rate",
    ]
    grouped = []
    for benchmark in sorted({r["benchmark"] for r in rows}):
        for dp in DP_PERIODS:
            group = [r for r in rows if r["benchmark"] == benchmark and r["dp_hours"] == dp]
            for metric in metrics:
                values = [float(r[metric]) for r in group]
                grouped.append(
                    {
                        "benchmark": benchmark,
                        "dp_hours": dp,
                        "metric": metric,
                        "n": len(values),
                        "mean": statistics.fmean(values),
                        "median": statistics.median(values),
                        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
                        "min": min(values),
                        "max": max(values),
                    }
                )
    return grouped


def rank_values(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        rank = (i + j + 2) / 2
        for k in range(i, j + 1):
            ranks[order[k]] = rank
        i = j + 1
    return ranks


def corr(xs, ys):
    if len(xs) < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return float("nan")
    return float(np.corrcoef(xs, ys)[0, 1])


def correlation_rows(rows):
    predictors = [
        "phase1_final_edges",
        "phase1_edge_gain",
        "phase1_edge_last_hour_rate",
        "phase1_final_data",
        "phase1_data_gain",
        "phase1_data_gain_per_hour",
        "phase1_data_last_hour_rate",
        "phase1_final_corpus",
        "phase1_corpus_gain",
        "phase1_corpus_gain_per_hour",
        "phase1_corpus_last_hour_rate",
    ]
    outcomes = ["phase2_edge_gain", "final_edges"]
    scopes = [("all", rows)]
    scopes.extend((b, [r for r in rows if r["benchmark"] == b]) for b in sorted({r["benchmark"] for r in rows}))

    out = []
    for scope, scope_rows in scopes:
        for outcome in outcomes:
            ys = [float(r[outcome]) for r in scope_rows]
            for predictor in predictors:
                xs = [float(r[predictor]) for r in scope_rows]
                out.append(
                    {
                        "scope": scope,
                        "outcome": outcome,
                        "predictor": predictor,
                        "n": len(scope_rows),
                        "pearson_r": corr(xs, ys),
                        "spearman_r": corr(rank_values(xs), rank_values(ys)),
                    }
                )
    return out


def step_interpolate(rows, metric, grid):
    out = []
    j = 0
    last = rows[0][metric] if rows else 0
    for t in grid:
        while j < len(rows) and rows[j]["hours"] <= t:
            last = rows[j][metric]
            j += 1
        out.append(0 if last is None else last)
    return np.array(out, dtype=float)


def plot_aggregate_curves(benchmarks):
    colors = {2: "#1f77b4", 6: "#2ca02c", 24: "#d62728"}
    for benchmark in benchmarks:
        plotted = {}
        fig, ax = plt.subplots(figsize=(10.5, 5.5))
        for dp in DP_PERIODS:
            trials = []
            max_hours = 0.0
            for trial_num in range(1, NUM_TRIALS + 1):
                _, _, _, merged = load_trial(benchmark, dp, trial_num)
                trials.append(merged)
                max_hours = max(max_hours, merged[-1]["hours"])
            grid = np.linspace(0, max_hours, max(80, int(max_hours * 12)))
            matrix = np.vstack([step_interpolate(t, "edges", grid) for t in trials])
            median = np.median(matrix, axis=0)
            q1 = np.percentile(matrix, 25, axis=0)
            q3 = np.percentile(matrix, 75, axis=0)
            plotted[dp] = (grid, median, q1, q3)
            ax.plot(grid, median, color=colors[dp], label=f"{dp}+12h median", linewidth=2.0)
            ax.fill_between(grid, q1, q3, color=colors[dp], alpha=0.16, linewidth=0)
            ax.axvline(dp, color=colors[dp], linestyle=":", alpha=0.7, linewidth=2.5)
        ax.set_title(f"{benchmark}: median edge coverage with IQR across 9 trials")
        ax.set_xlabel("Wall-clock time (hours)")
        ax.set_ylabel("Edges hit")
        ax.grid(True, alpha=0.3)
        ax.legend()
        fig.tight_layout()
        out = ANALYSIS_PLOTS_DIR / f"{benchmark}_aggregate_edges.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=180)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(10.5, 5.5))
        ymin = float("inf")
        ymax = float("-inf")
        for dp, (grid, median, q1, q3) in plotted.items():
            keep = grid >= SKIP_MINUTES / 60
            ax.plot(grid[keep], median[keep], color=colors[dp], label=f"{dp}+12h median", linewidth=2.0)
            ax.fill_between(grid[keep], q1[keep], q3[keep], color=colors[dp], alpha=0.16, linewidth=0)
            ax.axvline(dp, color=colors[dp], linestyle=":", alpha=0.7, linewidth=2.5)
            ymin = min(ymin, float(np.min(q1[keep])))
            ymax = max(ymax, float(np.max(q3[keep])))

        # Annotate dp=24 growth between t=6h and t=24h on the zoomed plot
        grid24, median24, _, _ = plotted[24]
        idx_6 = int(np.argmin(np.abs(grid24 - 6.0)))
        idx_24 = int(np.argmin(np.abs(grid24 - 24.0)))
        val_at_6 = float(median24[idx_6])
        val_at_24 = float(median24[idx_24])
        delta = val_at_24 - val_at_6
        ax.scatter([6.0, 24.0], [val_at_6, val_at_24],
                   color=colors[24], s=70, zorder=5)
        ax.annotate("", xy=(24.0, val_at_24), xytext=(24.0, val_at_6),
                    arrowprops=dict(arrowstyle="<->", color=colors[24], lw=1.8))
        ax.text(24.3, (val_at_6 + val_at_24) / 2, f"+{delta:.0f} edges",
                color=colors[24], fontsize=9, va="center", ha="left",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.75, ec="none"))

        ax.set_ylim(ymin - 10, ymax + 10)
        ax.set_title(f"{benchmark}: median edge coverage after first {SKIP_MINUTES:.0f} minutes")
        ax.set_xlabel("Wall-clock time (hours)")
        ax.set_ylabel("Edges hit")
        ax.grid(True, alpha=0.3)
        ax.legend()
        fig.tight_layout()
        out = ANALYSIS_PLOTS_DIR / f"{benchmark}_aggregate_edges_zoomed.png"
        fig.savefig(out, dpi=180)
        plt.close(fig)


def plot_boxplots(rows):
    metrics = [
        ("final_edges", "Final edges hit", "final_edges_boxplot.png"),
        ("edges_at_14h", "Edges hit at common 14h budget", "edges_at_14h_boxplot.png"),
        ("phase2_edge_gain", "Edges gained during 12h LibAFL phase", "phase2_gain_boxplot.png"),
        ("total_edge_gain_per_hour", "Total edge gain per hour after first 10m", "efficiency_boxplot.png"),
    ]
    benchmarks = sorted({r["benchmark"] for r in rows})
    for metric, ylabel, filename in metrics:
        fig, axes = plt.subplots(1, len(benchmarks), figsize=(5.4 * len(benchmarks), 4.8), sharey=False)
        if len(benchmarks) == 1:
            axes = [axes]
        for ax, benchmark in zip(axes, benchmarks):
            data = [
                [float(r[metric]) for r in rows if r["benchmark"] == benchmark and r["dp_hours"] == dp]
                for dp in DP_PERIODS
            ]
            ax.boxplot(data, tick_labels=[str(dp) for dp in DP_PERIODS], showmeans=True)
            for i, values in enumerate(data, start=1):
                jitter = np.linspace(-0.08, 0.08, len(values))
                ax.scatter(np.full(len(values), i) + jitter, values, s=20, alpha=0.7)
            ax.set_title(benchmark)
            ax.set_xlabel("Diversification period (hours)")
            ax.set_ylabel(ylabel)
            ax.grid(True, axis="y", alpha=0.25)
        fig.tight_layout()
        out = ANALYSIS_PLOTS_DIR / filename
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=180)
        plt.close(fig)


def plot_runtime_signal_scatter(rows):
    predictors = [
        ("phase1_data_last_hour_rate", "Phase 1 data discoveries/hour in final hour"),
        ("phase1_corpus_last_hour_rate", "Phase 1 corpus additions/hour in final hour"),
    ]
    colors = {2: "#1f77b4", 6: "#2ca02c", 24: "#d62728"}
    benchmarks = sorted({r["benchmark"] for r in rows})
    fig, axes = plt.subplots(
        len(benchmarks),
        len(predictors),
        figsize=(11, 4.5 * len(benchmarks)),
        squeeze=False,
    )
    for row_idx, benchmark in enumerate(benchmarks):
        bench_rows = [r for r in rows if r["benchmark"] == benchmark]
        for col_idx, (metric, xlabel) in enumerate(predictors):
            ax = axes[row_idx][col_idx]
            for dp in DP_PERIODS:
                group = [r for r in bench_rows if r["dp_hours"] == dp]
                ax.scatter(
                    [float(r[metric]) for r in group],
                    [float(r["phase2_edge_gain"]) for r in group],
                    label=f"{dp}h DP" if row_idx == 0 and col_idx == 0 else None,
                    color=colors[dp],
                    alpha=0.75,
                )
            ax.set_title(f"{benchmark}")
            ax.set_xlabel(xlabel)
            ax.set_ylabel("Phase 2 edge gain")
            ax.grid(True, alpha=0.25)
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = ANALYSIS_PLOTS_DIR / "runtime_signal_scatter.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180)
    plt.close(fig)


def write_markdown_summary(grouped, correlations):
    lines = [
        "# Trial Analysis Summary",
        "",
        "Each configuration has 9 trials. Gains are measured after skipping the first 10 minutes of phase 1 to avoid the initial seed-corpus burst.",
        "",
        "## Edge Outcomes",
        "",
        "| Benchmark | DP | Final edges median (14h common budget) | Phase 2 gain median | Total gain/hour median |",
        "|---|---:|---:|---:|---:|",
    ]
    lookup = {(r["benchmark"], r["dp_hours"], r["metric"]): r for r in grouped}
    for benchmark in sorted({r["benchmark"] for r in grouped}):
        for dp in DP_PERIODS:
            final_edges = lookup[(benchmark, dp, "final_edges")]["median"]
            edges_at_14h = lookup[(benchmark, dp, "edges_at_14h")]["median"]
            phase2_gain = lookup[(benchmark, dp, "phase2_edge_gain")]["median"]
            efficiency = lookup[(benchmark, dp, "total_edge_gain_per_hour")]["median"]
            lines.append(
                f"| {benchmark} | {dp} | {final_edges:.0f} "
                f"(14h: {edges_at_14h:.0f}) | {phase2_gain:.0f} | {efficiency:.2f} |"
            )

    lines.extend(
        [
            "",
            "## Strongest Runtime-Signal Correlations",
            "",
            "Spearman correlation is shown because the relationship does not need to be linear. Positive values mean larger phase-1 signal values are associated with larger outcomes.",
            "",
            "| Scope | Outcome | Predictor | Spearman r | Pearson r |",
            "|---|---|---|---:|---:|",
        ]
    )
    usable = [r for r in correlations if not math.isnan(r["spearman_r"])]
    usable.sort(key=lambda r: abs(r["spearman_r"]), reverse=True)
    for row in usable[:12]:
        lines.append(
            f"| {row['scope']} | {row['outcome']} | {row['predictor']} | "
            f"{row['spearman_r']:.3f} | {row['pearson_r']:.3f} |"
        )

    path = ANALYSIS_DIR / "summary.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    global SKIP_MINUTES

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-minutes", type=float, default=SKIP_MINUTES)
    args = ap.parse_args()

    SKIP_MINUTES = args.skip_minutes

    benchmarks = sorted(p.name for p in TRIALS_DIR.iterdir() if p.is_dir())
    rows = []
    for benchmark in benchmarks:
        for dp in DP_PERIODS:
            for trial_num in range(1, NUM_TRIALS + 1):
                rows.append(summarize_trial(benchmark, dp, trial_num))

    summary_fields = list(rows[0].keys())
    write_csv(ANALYSIS_DIR / "trial_summary.csv", rows, summary_fields)

    grouped = group_stats(rows)
    write_csv(ANALYSIS_DIR / "group_stats.csv", grouped, list(grouped[0].keys()))

    correlations = correlation_rows(rows)
    write_csv(ANALYSIS_DIR / "runtime_signal_correlations.csv", correlations, list(correlations[0].keys()))

    plot_aggregate_curves(benchmarks)
    plot_boxplots(rows)
    plot_runtime_signal_scatter(rows)
    write_markdown_summary(grouped, correlations)

    print(f"Wrote tables to {ANALYSIS_DIR}")
    print(f"Wrote plots to {ANALYSIS_PLOTS_DIR}")


if __name__ == "__main__":
    main()
