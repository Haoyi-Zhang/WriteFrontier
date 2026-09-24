# Trace-perturbation sensitivity protocol

The perturbation suite is a selection-sensitivity test, not a new production trace. Starting from the distributed trace-derived segment table, it runs the unchanged trace-study grid on five deterministic transformations:

1. `scale_x2`: doubles source and live bytes, testing scale handling.
2. `retention_half`: halves live bytes, testing a more aggressive invalidation/liveness proxy.
3. `retention_high`: raises live bytes toward the source footprint, testing a conservative liveness proxy.
4. `reverse_order`: reverses segment order within each natural trace/window group.
5. `fixed_shuffle`: applies a fixed-seed within-group permutation and reassigns the ordinal field.

All transformations preserve `0 <= live_bytes <= source_bytes`. No result is used to select or tune an algorithm. Canonical inputs, logs, outputs, and the manifest are under `artifact/results/trace-perturbation/`; `artifact/run_trace_perturbations.py` regenerates the suite.
