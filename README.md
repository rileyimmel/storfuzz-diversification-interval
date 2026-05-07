# When Should StorFuzz Switch?

Studying diversification interval length and runtime signals for [StorFuzz](https://github.com/rub-softsec/storfuzz).

This is the project artifact for my UVA course project. It contains the code, processed trial data, plots, and the rendered paper for an empirical study of how long StorFuzz should run in diversification mode before switching back to LibAFL on the HarfBuzz and OpenThread benchmarks.

The full paper is in [When-Should-StorFuzz-Switch.pdf](When-Should-StorFuzz-Switch.pdf).

## What is in this repo

```
.
├── When-Should-StorFuzz-Switch.pdf  Rendered paper
├── analyze_trials.py                Reduces raw trial logs into the CSV summaries in analysis/
├── plot_trials.py                   Per-trial edge-coverage plots
├── plot_coverage.py                 Aggregate edge-coverage plots and boxplots used in the paper
├── analysis/                        Processed CSVs
│   ├── trial_summary.csv                One row per (benchmark, dp_hours, trial)
│   ├── group_stats.csv                  Aggregated statistics per (benchmark, dp_hours)
│   ├── runtime_signal_correlations.csv  Spearman/Pearson correlations for runtime signals
│   └── summary.md                       Human-readable summary of the above
└── plots/                           Figures used in the paper, plus per-trial diagnostic plots
```

The raw fuzzing logs (~86 GB) are intentionally not included. Every figure, number, and table in the paper can be reproduced from the CSVs in `analysis/`.

## Reproducing the analysis

The CSVs in `analysis/` and the figures in `plots/` are the ones used in the paper. To regenerate them from raw trial logs (not included), the workflow is:

```bash
python analyze_trials.py --trials-dir <path-to-trials> --out-dir analysis
python plot_coverage.py  --trials-dir <path-to-trials> --out-dir plots/analysis
python plot_trials.py    --trials-dir <path-to-trials> --out-dir plots
```

Each `trials/<benchmark>/dp<H>_trial<N>/` directory follows the layout produced by the trial wrapper (a `phase1_diversify/` and `phase2_libafl/` pair with `stats.toml` files plus a top-level `trial_info.txt`).

## Experimental setup, in brief

- Two benchmarks from the StorFuzz paper: HarfBuzz (`hb-shape-fuzzer`) and OpenThread.
- Three diversification periods: 2 h, 6 h, 24 h, each followed by a fixed 12 h LibAFL phase (the 2+12, 6+12, and 24+12 configurations).
- 9 independent trials per (benchmark, diversification period) for 54 trials total.
- Edge coverage is the primary metric. Data coverage and corpus growth are tracked as candidate runtime signals.

See the PDF for the full setup, results, and discussion.

## Citing the StorFuzz paper

This project builds on:

> Leon Weiß, Tobias Holl, and Kevin Borgolte. **StorFuzz: Using Data Diversity to Overcome Fuzzing Plateaus.** *Proceedings of the 48th IEEE/ACM International Conference on Software Engineering (ICSE)*, 2026. doi: [10.1145/3744916.3773179](https://doi.org/10.1145/3744916.3773179)
