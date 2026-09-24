# Literature calibration and novelty boundary

## Scope and method

This audit calibrates the paper against a fixed 22-paper corpus: twelve FAST
papers, five influential/core papers, and five adjacent systems papers. The
selection covers log cleaning and LSM rewriting, flash-aware placement, tiered
key-value stores, cache admission/replacement, crash semantics, and analytical
optimization. Separate closest-theory records cover storage reallocation,
stock-size ordering, component dynamization, and offline/online SSD management.

For each corpus paper, an official or author-hosted full paper was opened and
section-level inspection was completed for the passages listed below; official
landing pages or DOI records were used to verify bibliographic metadata. This
is not a claim that every sentence was read or that the corpus is a systematic
review of all storage literature. No scholarly PDF is redistributed. Exact
URLs, access mode, access date, licenses, and input integration are recorded in
`external_resources.csv`.

The audit was used adversarially. A relationship is retained only when the
operation set, comparator, persistence semantics, and evidence actually differ.
Similarity of terminology is not treated as novelty.

## Twenty-two-paper pattern matrix

| ID | Work | Inspected sections | General principle and argument | Evaluation / artifact pattern | Constraint on this paper |
|---:|---|---|---|---|---|
| F1 | WiscKey, FAST'16 | Abstract; introduction; architecture; GC; recovery; evaluation | Separate large values from the LSM tree to avoid value rewrites; combine design argument with recovery/GC mechanisms | Prototype, SSDs, workloads, architecture and WA figures | Data separation and reduced rewriting are established systems mechanisms; this paper cannot claim them |
| F2 | SpanDB, FAST'21 | Introduction; bottleneck study; design; implementation; evaluation | Place WAL and LSM components across hybrid media according to bottlenecks | End-to-end KV store, YCSB/production-inspired workloads, latency and throughput | A genuine hybrid-tier benefit claim requires an implementation and workload evidence absent here |
| F3 | SLM-DB, FAST'19 | Introduction; data layout; index; recovery; evaluation | Use persistent memory to build a single-level KV organization | Prototype, recovery path, microbenchmarks and YCSB | Calibrates the bar for persistent-tier and concrete recovery claims |
| F4 | SepBIT, FAST'22 | Introduction; invalidation inference; placement; implementation; evaluation | Infer block invalidation time and separate data to reduce future GC copying | Multiple workloads/traces and devices; WA and prediction figures | Lifetime prediction changes placement and future recopying; frozen recovery epochs do not subsume it |
| F5 | MiDAS, FAST'24 | Introduction; WA definition; grouping model; adaptive configuration; evaluation | Adapt age-group number and size rather than use a fixed grouping | Broad workload study and system comparison | Application/user writes are the relevant denominator for system WAF; modeled migration traffic must be labeled separately |
| F6 | DOGI, FAST'26 | Introduction; oracle analysis; design; evaluation | Use an oracle to expose placement structure, then derive a practical approximation | Trace corpus, oracle gap, implementation and comparisons | Establishes an oracle-to-online evaluation pattern and points to broader SSD-management theory |
| F7 | MINOS, FAST'27 prepublication | Formal model; OP-minimized oracle; online approximation; implementation; evaluation | Optimize invalidation-time separation under limited streams, then approximate online | Reported 170 workloads and 500 TiB; theory-to-system narrative | Prevents a broad “theoretical WAF=1” or separation novelty claim; the present theorem concerns reserve/transaction fragmentation instead |
| F8 | F2FS, FAST'15 | Motivation; on-disk layout; cleaning; recovery; evaluation | Make a log-structured file system explicitly flash-aware | Full file system and flash benchmark suite | Supplies standard cleaning/recovery vocabulary and concrete-system evidence expectations |
| F9 | ARC, FAST'03 | Policy definition; adaptation; complexity; trace evaluation | Adapt between recency and frequency without workload-specific tuning | 23 traces and hit-ratio comparisons | A replacement-policy claim requires hit/miss traces and policy semantics; local batching proxies are not ARC alternatives |
| F10 | RIPQ, FAST'15 | Workload; framework; policy mappings; implementation; evaluation | Aggregate flash-cache writes while supporting priority-based replacement | Facebook photo trace, hit ratio, throughput and device concerns | Closest cache-policy/flash-write system; the paper's frozen retention excludes its policy tradeoff |
| F11 | CCFS, FAST'17 | Application consistency problem; stream semantics; implementation; crash/performance evaluation | Constrain ordering within streams while retaining cross-stream scheduling freedom | Applications, crash-consistency tests, file-system benchmarks | Concrete crash consistency requires application and file-system semantics; token-prefix checking supports only the abstract protocol |
| F12 | NoFS, FAST'12 | Ordering problem; dependency mechanism; correctness; evaluation | Replace global ordering with explicit dependencies | File-system prototype and performance evaluation | Shows that ordering itself can be a systems mechanism, but its semantics and implementation differ from prefix migration |
| C1 | LFS, TOCS'92 | Architecture; segment cleaning; recovery; simulation/evaluation | Append updates and reclaim segments through cleaning | Prototype, traces, cleaning-policy analysis | Foundational source for segment cleaning and write-cost terminology |
| C2 | LSM-tree, Acta Informatica'96 | Data structure; analytical cost; variants; applications | Batch updates through a hierarchy of components | Analytical argument and application discussion | Foundational merge-cost model; an ordinary batching DP alone would not be a contribution |
| C3 | FSCQ, SOSP'15 | Crash Hoare Logic; verified components; extraction; benchmarks; limits | Prove concrete file-system crash safety with a machine-checked logic | Verified implementation plus performance evaluation | Sets a much stronger bar than the abstract retained-token invariant; the paper must not imply formal verification |
| C4 | CrashMonkey/B3, OSDI'18 | Crash-testing model; workload generation; implementation; bug study | Bound black-box crash exploration while preserving relevant write sequences | Multiple file systems and discovered bugs | Calibrates crash-prefix and negative-control language; this artifact is a reference model, not a bug finder |
| C5 | Monkey, SIGMOD'17 | Cost model; optimal allocation; implementation; evaluation | Derive an analytical optimum for Bloom-filter allocation, then validate in a KV store | Theory plus system benchmarks | Closest model-to-optimizer story; motivates a structural theorem beyond a generic shortest path |
| A1 | Flashield, NSDI'19 | Workload; admission model; architecture; implementation; evaluation | Admit objects predicted to be reused to control flash write rate | Production-derived traces and system prototype | Admission creates a variable retained set, an explicit mechanism excluded from this paper |
| A2 | Kangaroo, SOSP'21 | Workload constraints; two-part architecture; analysis; implementation; evaluation | Combine a small log and set-associative flash cache for tiny objects | Trace-driven/device evaluation and design tradeoffs | Closest tiered tiny-object cache; includes hit/DRAM/write tradeoffs absent from the model |
| A3 | SIEVE, NSDI'24 | Algorithm; analysis; library integrations; trace and throughput evaluation | Use a simple scan/reinsertion-style eviction primitive with low synchronization cost | 1,559 traces from seven sources and five production libraries | Demonstrates the evidence needed to call something an eviction policy; local “LRU-tiered” is therefore labeled a proxy |
| A4 | SILK, ATC'19 | Tail-latency diagnosis; scheduling design; implementation; evaluation | Schedule LSM compaction to protect foreground performance | RocksDB implementation, workload and latency evidence | Real compaction scheduling optimizes time and interference, not only frozen byte traffic |
| A5 | PebblesDB, SOSP'17 | Fragmented LSM structure; implementation; tradeoff analysis; evaluation | Use fragmented guard ranges to reduce write amplification | KV-store prototype and read/write/space tradeoff study | Closest compaction-layout alternative; the present model fixes layout and destination |

## Narrative and evidence patterns

The twelve FAST papers usually follow one of two patterns. Systems papers begin
with a concrete workload or device failure mode, derive a mechanism, describe a
prototype, and close with broad workload/device comparisons. Formal-model papers
state an explicit objective and comparator, derive an oracle or bound, then
connect it to an online system and empirical validation. Architecture figures
explain the mechanism; microbenchmarks isolate components; full-system plots
establish breadth; sensitivity tables expose tuning and cost assumptions.

The core papers make proof boundaries unusually visible. LFS and LSM define the
canonical rewrite/cleaning abstractions. Monkey shows how a cost model can lead
to an optimization result and still require system validation. FSCQ separates a
machine-checked crash theorem from performance engineering. CrashMonkey separates
bounded test coverage from proof. These distinctions directly shaped the claim
ledger.

The adjacent cache papers use hit ratio, request traces, device behavior,
throughput, latency, and implementation complexity as first-class outcomes.
Accordingly, this paper never interprets its eight public-input rows as workload
performance and never treats four deterministic batch endpoint rules as complete
cache policies.

## Closest-theory adversary

### Storage reallocation

*Cost-Oblivious Storage Reallocation* already models coexistence of old and new
copies across checkpointed mapping updates and analyzes additional workspace.
Therefore, “copy before reclaim needs temporary space” is not a novelty claim.
The present delta is the ordered two-source exchange structure, legal-step
confluence, separation of linear feasibility from transaction-fragmentation
cost, and the exact reserve/cost family under a declared recovery epoch.

### Alternating stock size

The arbitrary-selection all-live boundary becomes a signed-prefix stock-size
problem. Its direct 3-PARTITION construction is retained as a model
classification and negative control, not advertised as new complexity theory.
Oldest-prefix order removes the choice responsible for that boundary and is a
premise of the confluence theorem.

### Data-structure dynamization and SSD management

*Competitive Data-Structure Dynamization* studies online component rebuilding
under arrivals and component limits. *Offline and Online Algorithms for SSD
Management* and *Optimal SSD Management with Predictions* use broader SSD
management objectives and comparators. The recovery-epoch model has a frozen
set, no arrivals, no prediction interface, and no competitive ratio. It claims
neither an online compaction theorem nor superiority to those models.

## Exact closest-work delta

After the adversarial comparison, the defensible contribution is narrow:

1. **Model boundary:** two ordered logs, opposite destinations, frozen retained
   bytes, ideal aggregate capacity, and one copy--flush--atomic-commit--reclaim
   transaction per chosen oldest prefix.
2. **Safety result:** every legal prefix epoch from a completable state preserves
   completion. This yields a linear scan and local blocker, rather than a policy-
   dependent deadlock-avoidance problem.
3. **Cost result:** adjacent same-source epochs merge, so an optimum alternates;
   a polynomial dynamic program optimizes rounded payload plus commit traffic.
4. **Reserve result:** the per-source lower-bound basin is characterized, cost
   sublevel sets are upward-closed, and the symmetric unit-exchange family has
   the exact inverse-reserve staircase
   `(ceil(n/r)+1)(q+mu)` under `q>=2r`.
5. **Evidence result:** the theorem implementation is attacked by a complete
   254,016-instance grid, independent exact paths, a no-memo oracle, 2,953,804
   legal-edge closure checks, crash mutations, and clean-extraction reproduction.

The contribution does not include lifetime inference, admission, replacement,
physical stream assignment, early subextent reclaim, a device scheduler, online
arrivals, a competitive ratio, or measured cache/system benefit.

## Null hypotheses considered

- **Null 1: successful schedules have constant cost.** True for the rejected
  arbitrary-selection one-copy model and for the ordered model with exact bytes
  and free commits. Falsified for the selected model by legal costs 10 and 20.
- **Null 2: the result is only a generic shortest path.** The alternating normal
  form, confluence/linear feasibility, exact lower-bound basin, and unit-exchange
  closed form are independent structural statements. The DP is still standard
  shortest-path machinery once those statements define the graph.
- **Null 3: final fit or total reserve decides feasibility.** Rejected by exact
  blockers and direction-sensitive reserve frontiers.
- **Null 4: policy choice controls safety in the ordered model.** Rejected by the
  confluence proof and by zero violations across all audited viable edges.
- **Null 5: the abstract crash checker proves a real system safe.** Rejected. The
  checker assumes flush and atomic commit and excludes device/filesystem failure
  behavior below that interface.

## Reference count and citation discipline

The main bibliography contains 71 scholarly entries, all actually cited in the
main paper or supplement. It contains no `@misc` record and no repository URL as
a research citation. Count is not used as evidence of completeness. Citations
are assigned to specific mechanisms, models, or evidence patterns; papers are
not cited merely to inflate coverage. The 22-paper corpus is a calibration
sample, while the main bibliography also covers cache replacement, LSM design,
crash consistency, reallocation, SSD management, public traces, and supporting
abstractions.

`reference-audit.csv` records the canonical DOI, official scholarly page, or
ISBN for every entry and the 2026-09-16 verification basis.
`validate_reference_audit.py` checks uniqueness, required metadata, scholarly
type, and citation closure. The audit repaired inherited records for SSD
management, Featherstitch, DFSCQ, RocksDB, SCFTL, and several canonical
locators; it also removed code repositories from the scholarly bibliography.
This is a documented metadata audit, not a claim of independent systematic
review.

## Remaining external-use risks

The package is internally complete but has not undergone independent peer
review or proof-assistant checking. The principal external-review risk is
significance: a reviewer may judge the two-tier frozen episode too narrow for a
FAST long paper without a system prototype or broader model. That is not hidden
by the exhaustive small-domain evidence. A second risk is assumption
sensitivity: arbitrary selection, more than two cyclic tiers, changing
retention, early subextent reclaim, or non-atomic metadata can invalidate the
safety theorem. The paper states those exclusions explicitly.

Before submission, human authors should independently read the closest papers,
validate theorem proofs and code, decide whether the scoped contribution meets
the venue's significance bar, and satisfy current originality, authorship,
AI-use, anonymization, and resubmission policies. This audit is research support,
not an independent reviewer report or acceptance prediction.
