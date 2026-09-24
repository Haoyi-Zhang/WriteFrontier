# ReLoC: recovery-epoch frontiers for two ordered log tiers

This repository is the standalone artifact for **Write-Amplification Frontiers
in Capacity-Constrained Tiered Log-Structured Caches**. It implements the
ordered two-tier recovery-epoch model, exact optimizer, linear feasibility
certificate, deterministic policy proxies, crash-prefix checker, complete
bounded campaign, and a retained arbitrary-selection boundary model.

The artifact is standard-library Python. It requires no network, package
installation, GPU, model API, hidden cache, or parent project. It models byte
capacity and persistence order; it is not a production cache, filesystem, FTL,
or SSD benchmark.

## Main result encoded by the artifact

A state records how many oldest segments have committed from each tier. A legal
recovery epoch copies a nonempty remaining oldest prefix to the opposite tier,
flushes its retained payload, atomically commits one pointer set, and reclaims
the source prefix only afterward. Physical traffic is rounded payload plus one
commit charge.

Under the declared two-tier assumptions, every legal epoch from a completable
state preserves completion. Feasibility therefore has a linear scan and local
blocking certificate. Cost still depends on batch boundaries; an exact dynamic
program finds a minimum-cost alternating schedule. The supplied campaign
cross-checks that implementation against an unrestricted shortest path, a
project-local no-memo recursion, and a raw-tuple oracle that imports none of the
core model, capacity, cost, replay, or solver modules.  A backward confluence
audit, a 20,000-case metamorphic campaign, and a closed-form unit-exchange
family provide additional independent failure surfaces.

## Requirements and resource contract

- Linux with Python 3.10 or later; standard library only.
- Ordinary non-optimized Python. `python -O` is rejected because scientific
  assertions must remain enabled.
- One process bound to one available CPU.
- 3 GiB process address-space limit and 2,700-second CPU limit per invocation.
- The runner refuses to start or finish if its process reports nonzero swap.
- No command needs to run concurrently.

Runtime and peak memory are observations, not scientific outputs. Verifiers
remove runtime records before JSON comparison.

## Quick reproduction

Run from this repository root:

```sh
python -m unittest discover -s tests -v
python validate_reference_audit.py
python run.py --all --out reproduced
python verify_results.py results/frontier reproduced
python run_unordered_boundary.py --all --out reproduced-boundary
python verify_unordered_boundary.py results/unordered-boundary reproduced-boundary
```

The unit suite contains 48 tests. The core verifier checks 23 deterministic
scientific files, all 254,016 case identifiers, exact status/cost agreement,
linear-scan agreement, confluence closure, the unit-exchange formula, and the
recovery controls. The boundary verifier checks the retained 65,484-instance
arbitrary-selection corpus. Same-environment clean extraction is reproducibility
evidence, not an independent research replication.

Delete the two reproduced directories after comparison; the commands do not
modify `results/`.

## Sequential and resumable core route

The all-in-one runner performs the following sequence. The exact grid can be
regenerated in four replaceable shards:

```sh
python run.py --grid-part 0 --out reproduced
python run.py --grid-part 1 --out reproduced
python run.py --grid-part 2 --out reproduced
python run.py --grid-part 3 --out reproduced
python run.py --aggregate --out reproduced
python run.py --trace --out reproduced
python run.py --recovery --out reproduced
python run.py --sensitivity --out reproduced
python run.py --unit-exchange --out reproduced
python run.py --independent-audit --out reproduced
python run.py --finalize --out reproduced
python verify_results.py results/frontier reproduced
```

Aggregation fails on a missing shard, duplicate case identifier, wrong row
count, or incomplete case range. Re-running a shard replaces its two files
rather than appending rows.

## Repository map

- `src/epoch_model.py` - immutable segments, capacity identity, batch cost,
  replay, and serialization.
- `src/epoch_dp.py` - linear scan, alternating exact DP, unrestricted shortest
  path, project-local no-memo oracle, and confluence audit.
- `src/independent_audit.py` - separately implemented raw-tuple state search; it
  imports no project model, capacity, cost, replay, or solver module.
- `src/epoch_policies.py` - four deterministic legal-prefix batching proxies.
- `src/epoch_recovery.py` - retained-token crash-prefix model and four negative
  protocol mutations.
- `src/trace_model.py` - parsers and deterministic public-excerpt translation.
- `run.py` - four-part core campaign and all auxiliary controls.
- `verify_results.py` - scientific-output and invariant verifier.
- `proofs/recovery-epochs.md` - full handwritten proof companion.
- `results/frontier/` - retained core CSV/JSON outputs.
- `inputs/` - two exact public excerpts, provenance, licenses, and protocol
  declaration.
- `src/model.py`, `src/oracle.py`, `src/certificates.py`,
  `src/check_certificate.py`, `src/recovery.py` - arbitrary-selection boundary
  implementation.
- `run_unordered_boundary.py`, `verify_unordered_boundary.py`,
  `proofs/unordered-boundary.md`, `results/unordered-boundary/` - retained
  boundary campaign.
- `claim_evidence_ledger.csv` - claim-to-proof/check/result mapping.
- `reference-audit.csv` and `validate_reference_audit.py` - 71-record scholarly
  inventory plus standalone and optional manuscript-closure validation.
- `external_resources.csv` and `literature-audit.md` - provenance and closest-
  work calibration.
- `failure-log.md` - falsified formulations and repaired implementation faults.

## Core finite domain

Each tier has an ordered sequence of length one or two. Segment types are
`(occupied, live)` in

```text
(1,0) (1,1) (2,0) (2,1) (2,2) (3,1) (3,2) (3,3)
```

There are `8+8^2=72` sequences per tier and `72^2=5,184` ordered patterns.
Both initial free coordinates range from 0 through 6, producing 254,016 exact
instances at `q=4` and `mu=1`.

Retained outcomes include:

- 231,077 feasible and 22,939 infeasible instances;
- 8,407 instances whose final layout fits but no execution exists;
- 17,851 feasible instances whose optimum exceeds the per-source lower bound;
- zero normal-form/unrestricted/raw-oracle disagreements across the full grid;
- zero linear-scan/exact status disagreements;
- zero disagreements in 5,184 project-local no-memo checks;
- zero solver disagreements and zero violations of four metamorphic relations
  in 20,000 fixed-seed cases searched by the separate raw-tuple oracle;
- zero violations among 2,953,804 legal edges from 1,490,305 viable states;
- zero disagreements at 64 closed-form unit-exchange points; and
- a legal objective witness with costs 10 and 20 for the same instance.

These are exhaustive counts in the declared small integer domain, not estimates
of production workload frequency.

## Recovery checks

The reference protocol is copy, flush, atomic pointer-set commit, then source
reclaim. The retained corpus contains 1,024 schedules, 2,883 epochs, and 14,461
normal crash boundaries with zero retained-token failures. Four negative
controls produce 4,088 mutation runs and 69,320 mutation boundaries; every
mutated run has at least one detected failure.

The checker does not model torn sectors, controller caches, filesystem or FTL
reordering below the declared flush interface, physical power loss, checksums,
or restart idempotence. Its result is an abstract protocol invariant only.

## Public inputs and licensing

`inputs/cloudphysics-prefix.csv` is the upstream header plus first 128 rows of
libCacheSim's `data/cloudPhysicsIO.csv`, retained with its GPLv3 license text.
`inputs/twitter-cluster015-prefix.csv` is the first 128 rows of Twitter's
`cluster015` sample with a local header, retained with CC BY 4.0 attribution and
license text. `inputs/README.md` records URLs, Git blob identifiers, exact
selection rules, and access date.

The harness uses these excerpts only to check parsers, latest-version liveness,
segment sealing, capacity conversion, planner/checker composition, and policy
interfaces. It does not reconstruct upstream cache semantics and supports no
hit-rate, throughput, latency, or device-lifetime claim.

## Interpretation and non-claims

The policy labels are controlled batching proxies, not faithful end-to-end
implementations of LRU-tiered, leveled LSM, or size-tiered cache systems. The
exact optimizer is an offline oracle for a frozen cleaning barrier. The model
assumes two tiers, opposite destinations, oldest-prefix reclaim order, frozen
retention, ideal aggregate packing, and a correct atomic pointer-set interface.

The retained arbitrary-selection model demonstrates that removing oldest-prefix
order permits legal-choice deadlocks and a classical 3-PARTITION boundary. Its
completed one-copy schedules have constant payload cost, so it is not used as
the paper's optimization model.

## Reference-integrity check

`reference-audit.csv` inventories all 71 research references. Every row has a
canonical DOI, official scholarly page, or ISBN; no repository URL is counted as
a research reference. The default validator works in this standalone artifact.
In the full project, the stronger command below also proves exact key, title,
year, venue, locator, and citation closure against the paper sources:

```sh
python validate_reference_audit.py
python validate_reference_audit.py --bib ../paper/references.bib \
  --tex ../paper/main.tex ../paper/supplement.tex
```

The check detects structural and provenance drift; it does not replace reading
the cited work or independent novelty review.

## License

Project-authored code and documentation are covered by `LICENSE`. Included
public input excerpts remain subject to the upstream licenses copied under
`inputs/`. No third-party scholarly paper PDF or external implementation is
redistributed.
