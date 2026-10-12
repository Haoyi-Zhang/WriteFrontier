# Coalesced same-input portfolio

This supplemental comparison reuses all 7,496 frozen ordered-model inputs in
`results/policy-frontier/instances.json.gz`. It does not replace the raw
policy results, schemas, schedules or counterexamples.

`src/epoch_policies.py` adds pure adjacent same-source coalescing and five
separately named coalesced candidates: the four existing proxies and two-start
maximum-prefix. `coalesced_portfolio(instance)` selects by replayed
`(cost, epochs, candidate name)`. It imports no solver/oracle and never sees
OPT. This is offline: it may read the entire frozen queue and simulate multiple
candidates, incurring their planning work. It is not a causal/online or
no-lookahead policy. Coalescing can exceed a proxy's original fan-in rule, so these are variants,
not relabeled original policies. The new runner uses solvers only for evaluation
after candidate selection.

From the artifact directory, using ordinary Python 3.10+:

```sh
python -B -m unittest discover -s tests -p test_coalesced_portfolio.py -v
python -B -m unittest discover -s tests -p test_recovery_selectors.py -v
python -B -m unittest discover -s tests -p test_coalesced_runner.py -v
python -B run_coalesced_portfolio.py
python -B run_coalesced_portfolio.py --check-existing
python -B run_coalesced_portfolio.py --out results/coalesced-portfolio-reproduced --verify results/coalesced-portfolio
python -B run_coalesced_portfolio.py --print-table
```

The runner restricts output to `results/coalesced-portfolio*` siblings and
compares the four deterministic files for a separate reproduction. It produces:

- `instances.json.gz`: the exact original compressed input bytes.
- `coalesced-policy-costs.csv.gz`: 52,472 distinctly named supplemental rows,
  seven per input (five coalesced variants, raw portfolio and coalesced portfolio).
- `residual-witnesses.json.gz`: every remaining coalesced-portfolio gap, with
  the exact input, selected candidate and both replayable schedules.
- `summary.json`: per-domain counts, exact ratios and validation outcomes.

`--check-existing` reads all gzip records and replays every residual witness.
The stable publishable dataset is `results/coalesced-portfolio/`; a separate
reproduction directory is evidence only and is not a second release dataset.

On this retained domain the coalesced portfolio is cost-optimal on 5,184/5,184
small frontiers, 1,401/1,536 short cases, 626/768 long cases and 8/8 public episodes.
Short P95/max are 77/75 and 51/43; long P95/max are 15/14 and 33/25. All 277
residual cases remain available. Ratios use the same frozen episode OPT
denominator as the original comparison; P95 is nearest rank. Generated cases
reuse 256 short and 128 long patterns under six cost models, not independent
workloads.

The new schema explicitly distinguishes minimum epochs **among minimum-cost
schedules** from global minimum epochs. The latter is evaluated with exact-byte
traffic and a unit commit: total retained payload is constant, so cost equals
that payload plus epoch count. They differ on 61 short and 139 long costed cases.
Original `opt_epochs` fields are unchanged.

Recovery now rejects unknown or non-string mutation selectors before consuming
the schedule or simulating events. The four controls and all-dead truncation
skips are unchanged. Torn-commit recovery uses an abstract invalid-record marker,
not a computed checksum. This is a Python model comparison and abstract recovery
check, not native storage, hardware, power-loss or production evidence. No timer
campaign is included.
