# Trial Analysis Summary

Each configuration has 9 trials. Gains are measured after skipping the first 10 minutes of phase 1 to avoid the initial seed-corpus burst.

## Edge Outcomes

| Benchmark | DP | Final edges median (14h common budget) | Phase 2 gain median | Total gain/hour median |
|---|---:|---:|---:|---:|
| harfbuzz | 2 | 4763 (14h: 4763) | 236 | 28.49 |
| harfbuzz | 6 | 4777 (14h: 4761) | 129 | 22.89 |
| harfbuzz | 24 | 4786 (14h: 4697) | 51 | 11.47 |
| openthread | 2 | 4765 (14h: 4765) | 34 | 7.81 |
| openthread | 6 | 4777 (14h: 4772) | 24 | 5.95 |
| openthread | 24 | 4780 (14h: 4764) | 4 | 3.04 |

## Strongest Runtime-Signal Correlations

Spearman correlation is shown because the relationship does not need to be linear. Positive values mean larger phase-1 signal values are associated with larger outcomes.

| Scope | Outcome | Predictor | Spearman r | Pearson r |
|---|---|---|---:|---:|
| harfbuzz | phase2_edge_gain | phase1_edge_gain | -0.975 | -0.982 |
| harfbuzz | phase2_edge_gain | phase1_final_edges | -0.970 | -0.991 |
| all | phase2_edge_gain | phase1_final_edges | -0.940 | -0.988 |
| harfbuzz | phase2_edge_gain | phase1_final_corpus | -0.939 | -0.963 |
| harfbuzz | phase2_edge_gain | phase1_data_gain | -0.928 | -0.936 |
| harfbuzz | phase2_edge_gain | phase1_corpus_gain | -0.925 | -0.941 |
| harfbuzz | phase2_edge_gain | phase1_final_data | -0.920 | -0.960 |
| harfbuzz | phase2_edge_gain | phase1_data_last_hour_rate | 0.910 | 0.854 |
| harfbuzz | phase2_edge_gain | phase1_corpus_last_hour_rate | 0.877 | 0.834 |
| openthread | phase2_edge_gain | phase1_final_edges | -0.865 | -0.867 |
| all | phase2_edge_gain | phase1_data_gain_per_hour | 0.864 | 0.951 |
| all | phase2_edge_gain | phase1_corpus_gain_per_hour | 0.863 | 0.947 |
