# Independent Blind-Review Audit Protocol

This directory is generated from the final artifact rather than from manuscript claims.

## Scope

The audit covers bibliography closure and resolver evidence, citation contexts, source and test inventory, deterministic-result hazards, all parseable trace-policy observations, groupwise sensitivity, and a fixed development/holdout diagnostic. It does not turn proxy traces into production measurements.

## Anti-overfitting interpretation

The exact dynamic programs optimize each declared instance and the comparison policies are deterministic rules; no statistical model is trained. Overfitting can nevertheless enter through workload, parameter-grid, window, metric, or figure selection. The audit therefore includes every parseable result row, reports all policy/grid groups, and applies a fixed hash partition over natural trace/window identifiers. This partition is not used to choose algorithms or parameters.

## Generated evidence

- `reference-audit-final.csv`: one row per bibliography entry with DOI, official URL, ISBN, or retained audit evidence.
- `citation-contexts.csv`: every citation occurrence with file, section, and sentence context.
- `policy-robustness.csv`: aggregate paired cost ratios and deterministic bootstrap intervals.
- `groupwise-robustness.csv`: results for every observed workload and parameter group.
- `development-holdout.csv`: fixed, untuned partition diagnostic.
- `normalized-policy-observations.csv`: the complete normalized input to the robustness calculations.
- `code-inventory.csv`: source and test line inventory with hashes.
- `determinism-static-scan.csv`: review targets, not automatically classified defects.

The machine-readable summary records 0 normalized policy observations across 0 policy labels and 20 tabular sources. Empty output means the corresponding canonical result table was not parseable and is a gate failure, not evidence of robustness.
