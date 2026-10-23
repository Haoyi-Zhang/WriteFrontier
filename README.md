# ReLoC: recovery-epoch frontiers for two ordered log tiers

This repository is the standalone artifact for **Write-Amplification Frontiers
in Capacity-Constrained Tiered Log-Structured Caches**. It implements the
ordered two-tier recovery-epoch model, exact optimizer, linear feasibility
certificate, deterministic policy proxies, crash-prefix checker, complete
bounded campaign, and a retained arbitrary-selection boundary model.

The core experiments use standard-library Python. They require no network, package
installation, GPU, model API, hidden cache, or parent project. The model concerns byte
capacity and persistence order; it is not a production cache, filesystem, FTL,
or SSD benchmark.

## Statistical figures

The optional `plots/draw_frontiers.py` helper renders the retained reserve/epoch
and slack curves from `results/frontier/unit-exchange-frontier.csv` and
`results/frontier/slack-curve.csv`. It writes PDFs directly with Matplotlib,
embedding STIX text and math without invoking TeX. Install
`requirements-figures.txt` for figure authoring; core experiments and tests
remain standard-library only. No font files are bundled.

From this repository, run `python plots/draw_frontiers.py --output-dir figures`.
It writes `unit-frontier.pdf` and `slack-curve.pdf` as vector graphics, without
rerunning the campaigns. The first curve plots minimum recovery epochs for
128 unit-live segments per tier. The second plots the percentage of the 5,184
retained patterns reaching the lower bound within an additional total-reserve
budget. Plotting preserves the recorded points; it does not estimate runtime
performance.

`python figures/draw_schematics.py --out figures` directly redraws the symbolic
recovery protocol and exact cost witness as vector PDFs.

## Main result encoded by the artifact

`analyze_planning_cost.py` validates the retained 20-case, 300-trial file
campaign, including its seven executed source/input bindings, then reports
planning median/P95 and per-trial plan-plus-execute medians. It does not run
timers or change the measured data. All three policies have identical file
write bytes on those 20 cases; modeled residual savings over the coalesced
portfolio come from the separate longer-queue domain, not these timings.

```sh
python -B analyze_planning_cost.py
python -B -m unittest discover -s tests -p test_planning_cost.py -v
```

In the full project, `python -B analyze_planning_cost.py --tex
../paper/tables/planning-cost.tex --check` verifies the actual paper table.

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

The abstract incremental feasibility loop takes linear arithmetic steps and
constant working registers, excluding input and output certificate. The checked
`scan_feasibility` routine additionally calls `final_free` and `replay` on
successful completion. Their prefix arrays and per-epoch replay records use
linear auxiliary validation space. Those checks are retained in the artifact.

## Capacity events and identical-information greedy comparison

The separate offline coalesced portfolio and its full retained-input comparison
are documented in [Coalesced same-input portfolio](README-coalesced-portfolio.md).
That usage guide explains the new rows, conditioned epoch metric, residual
gaps and reproduction commands; original raw policy results remain unchanged.

`reserve_thresholds` derives all nonnegative capacity events from the FIFO
guards. A source-0 edge needs `f1 >= L0(end)-B1(j)` and a source-1 edge
needs `f0 >= L1(end)-B0(i)`. The starting live prefix cancels. Rounding a
reserve coordinate down to its preceding event preserves the entire legal
graph and costs. Budget splits and Pareto frontiers now enumerate event
corners, not every allocation unit. Common-slack search binary-searches its
event list with the linear feasibility scan and runs the cost DP once.
This removes numeric-capacity iteration, not polynomial dependence on queue
lengths; the number of event corners can still be large.

`maximum_prefix_start` greedily takes the largest legal prefix, alternating
source preference and falling back if blocked or exhausted.
`two_start_maximum_prefix` simulates both starting preferences and retains
the cheaper complete schedule. Both see exactly the DP's frozen input.
The historical four-proxy interface and its retained files are unchanged;
the new baseline is compared in a separate campaign:

```sh
python -B -m unittest discover -s tests -p test_frontier_events.py -v
python -B run_policy_frontier.py
```

The campaign retains `results/policy-frontier/instances.json.gz`,
`policy-costs.csv.gz`, `summary.json`, and counterexample `witnesses.json`.
It reruns all 5,184 retained frontier inputs, all eight public episodes, and
adds 1,536 and 768 costed episodes with 3--12 and 16--32 segments per tier.
These are 256 and 128 generated ordered patterns under six cost models,
not 2,304 independent workloads. Large-queue cost models use scaled quanta
and commit charges. All seven policy costs are retained with the exact
minimum; both DPs and the separate raw-tuple oracle agree in all 7,496 cases.

Two-start is optimal on all 5,184 small frontiers and eight public episodes.
Those domains show no DP cost benefit over it. It is optimal on 1,315/1,536
short generated cases and 500/768 long generated cases; maximum exact ratios
are `51/43` and `325/231`. These are modeled-cost observations, not speed,
cache hit-rate, production traffic, or an approximation guarantee.

`src/destination_model.py` uses primitive tuples to check fixed multi-tier
routes. A simple cycle has distinct destinations and the FIFO exchange proof
still applies. The actual counterexample is shared-destination competition:
three singleton live-unit queues, routes `(2,2,1)`, reserve `(0,0,1)`.
Order `1,2,0` completes; the legal first action 0 strands sources 1 and 2.
The campaign also checks 1,728 three-cycle instances, with zero violations
among 11,580 legal edges from 7,724 viable nonterminal states.

The storage-operation contract is stated in the paper: occupied and retained
sizes must include allocation overhead; the allocator must realize aggregate
reserve; flush must precede atomic recovery publication; committed outputs
must remain; metadata capacity is separate. For `q=1`, allocation-unit traffic
has an exact occupancy correspondence. For `q>1`, transfer rounding is valid
only when output occupancy remains live size. Page-rounded output allocation
would change the capacity guard. The optional file executor below implements
the exact-unit application-write slice of this operation.

## File-API replay

The standard-library executor reserves disjoint 512-byte destination units,
copies retained payload, returns from payload sync before writing and syncing
one fixed 512-byte descriptor, then logically releases the old source prefix.
A frozen manifest and committed descriptors reconstruct record locations.
The descriptor area is reserved separately. This is a file-API contract;
filesystem/controller writes and physical power-loss behavior require
lower-layer validation.

`results/file-io-calibration/` contains 300 actual trials: the first 16 retained
longer-queue inputs with `q=1, mu=1`, three reserve controls, and one all-dead
control; three planners; five fresh repetitions with rotating order. Every
reopened payload verifies and measured successful episode writes equal the
declared cost. Two-start, coalesced portfolio and DP tie on write bytes in all
20 inputs. The 16-unit all-live controls use 17, 5 and 2 epochs at reserve
1, 4 and 16, writing 25,088, 18,944 and 17,408 bytes respectively.
Initialization, planning and reopen verification remain separately recorded.

The saved host is CPython 3.12.14 on Windows 11 Pro 10.0.28000, an i7-12700KF,
and NTFS on a Micron 3400 NVMe device. Both arenas share this device. Ordinary
OS caching and approximately 69% observed system CPU activity prevent small
timing differences from establishing a policy ranking. No dependency install
is needed. Executed source/input bindings use documented UTF-8/LF normalization
for text so that public checkout line endings do not invalidate the record.

```sh
python -B -m unittest discover -s tests -p 'test_file_io*.py' -v
python -B verify_file_io_measurements.py
python -B run_file_io_calibration.py --out file-io-observations
```

The first two commands check the adapter and saved observations, without
retiming. The last command measures a new, previously absent output directory
on the invoking machine; it does not reproduce the old host's elapsed times.
Eleven adapter tests include twelve actual child-process exit/reopen boundaries;
four additional methods check the saved packet, missing/duplicate trials,
false reopened results, modified byte counts, and modified summaries.

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
python verify_ordered_certificate.py results/frontier/ordered-blocking-certificate.json
python run_unordered_boundary.py --all --out reproduced-boundary
python verify_unordered_boundary.py results/unordered-boundary reproduced-boundary
```

The historical unit suite contained 69 tests, including six exact gain/write scoring
regressions. Gain/write compares rational scores exactly; positive occupied
gain at zero cost ranks first, with the documented tie rules unchanged.
The core verifier checks 24 deterministic
top-level scientific CSV/JSON files, all 254,016 case identifiers, exact
status/cost agreement, linear-scan agreement, the independent ordered blocking
certificate, confluence closure, the trace metric contract, the unit-exchange
formula, and the recovery controls. It rejects unexpected top-level scientific
files; only declared log/text files and the runtime/logs directories are
auxiliary exceptions. The boundary verifier checks the retained 65,484-instance
arbitrary-selection corpus. Same-environment clean extraction is reproducibility
evidence, not an independent research replication.

Keep the reproduced outputs for inspection; the commands do not modify
`results/`. Retained runtime records describe the historical host, not the
timing or memory use of a new run.

Both exact solvers now prepare occupied/live prefixes once for their state
loops and compute the same free-space identity directly. Public `free_at`,
independent replay and the raw-tuple oracle are unchanged. This removes repeated
prefix scans, not layer sorting or transition enumeration, and makes no measured
runtime/device claim. Frozen results remain tied to the preceding sources.
Three new current-only standard-library regressions are included by the existing
unit discovery and scientific CI (72 source methods before the metadata-semantics
additions below):

```sh
python -B -m unittest discover -s tests -p test_prepared_prefixes.py -v
```

They use owned tiny integer tiers, an independent all-schedule recursive
definition, all prefix states (including unreachable ones), rounding/dead
payload controls and budget exhaustion. A current test success is not a fresh
full-grid/recovery reproduction or a proof of the general theorems.

The `scientific-checks.yml` workflow runs the same unit tests, reference-inventory
check, complete core and arbitrary-selection campaigns, and result verifiers
from this flat repository root. It uses Ubuntu 24.04, one available CPU, a
3 GiB process address-space limit, and a 45-minute whole-run timeout. Its raw
outputs and logs are uploaded even after a failed scientific gate. Workflow
results are separate from local checks.

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
  path, project-local no-memo oracle, ordered blocking-certificate construction,
  and confluence audit.
- `src/check_ordered_certificate.py` and `verify_ordered_certificate.py` -
  independent ordered-model blocker reconstruction and CLI verification.
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
- zero disagreements in 5,184 project-local no-memo checks, one for every
  pattern at the maximal reserve corner `(6,6)`; all 5,184 are feasible with
  `OPT=LB`, and these checks are not the minimal-reserve frontier;
- zero solver disagreements and zero violations of four metamorphic relations
  in 20,000 fixed-seed cases searched by the separate raw-tuple oracle, using
  seed `20260916` and reserve components sampled in `[0,12]`;
- zero violations among 2,953,804 legal edges from 1,490,305 nonterminal viable
  prefix-state instances;
- zero disagreements at 64 closed-form unit-exchange points; and
- a legal objective witness with costs 10 and 20 for the same instance.

These are exhaustive counts in the declared small integer domain, not estimates
of production workload frequency.

The legacy JSON field `confluence_audit.viable_states` counts nonterminal viable
prefix-state instances, summed across the declared grid. Terminal states are
excluded because they have no outgoing edges. The field name and numerical
results are unchanged.

## Recovery checks

The reference protocol is copy, flush, atomic pointer-set commit, then source
reclaim. The retained corpus contains 1,024 schedules, 2,883 epochs, and 14,461
normal crash boundaries with zero retained-token failures. Three negative controls run on all 1,024 schedules. Persisted-payload
truncation runs on 1,016 schedules and records eight skips for all-dead inputs;
there is no retained token to truncate in those samples. The 4,088 executed
mutation runs cover 69,320 boundaries and every executed run has at least one
detected failure. Payload truncation is retained-token loss, not a synthetic
pointer-set omission.

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

The harness retains both raw live payload bytes and the sum of live payload
rounded separately for each segment to the allocation unit.  Trace reserve is
the asymmetric final-fit lower-bound vector plus the least common feasible
slack; it is not an equal initial reserve.  The result CSV labels both byte
fields and reports separate physical/raw and physical/allocation ratios.

The trace constructor requires `dataset_id`; instance labels have the form
`<dataset_id>-window-<index>-extra-<slack>`. Each stored certificate label uses
its enclosing `dataset` identity, distinguishing both excerpts even at the same
window and slack. The eight retained labels are aligned with this convention
by a metadata-only correction; schedules, costs, other fields, input provenance,
and historical runtime records are unchanged. This is not a fresh measurement
or trace campaign.

Seven current metadata regressions check tiny owned request windows under both
dataset identities, identity-only schedule/cost invariance, the eight retained
labels, and the nonterminal count convention:

```sh
python -B -m unittest discover -s tests -p test_metadata_semantics.py -v
```

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
