# Failure and repair log

This log records material research and implementation failures rather than
hiding them behind the final positive result.

1. **Fixed-output objective collapse.**  The first formulation assigned each
   run a fixed destination and copied every retained byte exactly once.  Every
   successful schedule therefore had identical payload and publication cost;
   it was a feasibility problem, not a write-amplification optimizer.  Repair:
   replace per-run publication with recovery epochs whose batching changes page
   rounding and commit cost.  The old formulation remains only as an unordered
   boundary regression.
2. **Incorrect expectation of greedy deadlock.**  Early examples from the
   arbitrary-selection model suggested that an ordered-prefix policy might
   strand a feasible instance.  Exact search found no such case.  The failed
   search prompted the legal-step confluence theorem; 2,953,804 legal edges
   leaving viable bounded states were then audited with zero counterexamples.
3. **Recovery checker duplicated batch pointers.**  An initial checker treated
   a multi-segment commit as repeated pointer publications and could overcount
   selected copies.  Repair: represent the batch commit as one atomic pointer
   set and assert token uniqueness.  Unit tests and all crash-prefix results
   were regenerated.
4. **Single-process campaign exceeded the interactive tool window.**  No
   scientific run exceeded the project's 45-minute bound, but a combined
   invocation crossed the shell-tool response window after its first partition.
   Repair: deterministic four-part grid execution with explicit part IDs and a
   separate aggregation step.  Part files are independently resumable.
5. **Public samples are too small for workload claims.**  Repository APIs made
   small exact excerpts available, not the full multi-terabyte corpora.  Repair:
   use them only as parser/mechanism tests and make that limitation explicit in
   the paper, README, provenance, and claim ledger.
6. **Shared-model exactness risk.**  The alternating DP, unrestricted DP, replay,
   and project-local no-memory recursion initially shared model and cost helpers,
   so agreement could miss a common encoding error.  Repair: add
   `src/independent_audit.py`, a raw-tuple search that imports none of those
   modules, run it on every one of the 254,016 grid cases, and add a 20,000-case
   fixed-seed campaign covering tier swap, reserve monotonicity, scale
   invariance, and adjacent-batch merging.  All recorded disagreement and
   violation counts are zero; this remains finite checking, not a proof.
7. **Inherited bibliography contained substantive metadata errors.**  The
   inherited records misattributed both SSD-management papers, used a wrong DOI
   for Featherstitch, conflated DFSCQ with another paper, assigned RocksDB to the
   wrong venue and pages, gave SCFTL the wrong pages, and paired a FlyTrap label
   with an unrelated URL.  Repair: verify canonical DOI or official scholarly
   records, replace the conflated FlyTrap item with the peer-reviewed Chipmunk
   paper actually used by the argument, remove repository records from the
   scholarly bibliography, and retain a 71-row machine-checkable reference
   audit.  The audit checks metadata and citation closure; it does not establish
   novelty by itself.
8. **Deserializer and result-contract gaps.**  Concrete pre-repair checks showed
   that a third tier was ignored and that Boolean or fractional numeric fields
   could be accepted through `int(...)`; extra top-level CSV/JSON outputs were
   also not rejected.  Repair: validate an exactly-two-tier integer schema
   before conversion, add round-trip and rejection tests, and enforce an exact
   24-file scientific output set with only documented runtime/log auxiliaries.
9. **Reporting drift in trace and recovery summaries.**  The trace table mixed
   raw retained payload with per-segment allocation-rounded bytes and described
   common slack above final fit as equal initial reserve.  The recovery table
   also obscured the eight all-dead skips by averaging 4,088 mutation runs.
   Repair: retain and verify both byte fields, generate asymmetric free vectors
   from the final-fit base plus common slack, and generate per-mutation counts
   directly from the recovery result.

