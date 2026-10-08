# Recovery-epoch model: definitions, theorems, and certificates

This file is the proof companion to `src/epoch_model.py`,
`src/epoch_dp.py`, and `src/epoch_recovery.py`. All capacities and costs are
non-negative integers. The model is an abstract byte-accounting and persistence
model; it is not a claim about any particular filesystem, SSD, flash translation
layer, or power-failure contract.

## 1. Ordered two-tier model

There are two source tiers, `s in {0,1}`. Tier `s` contains immutable segments
`x_{s,1},...,x_{s,n_s}` in oldest-first reclaim order. Segment `x` occupies
`b(x)>0` units in its source and has `0 <= l(x) <= b(x)` retained units that
must be copied to the other tier. Its remaining bytes are dead and need not be
copied. The initial free vector is `(f_0,f_1)`.

A **recovery epoch** chooses a non-empty prefix of the unprocessed segments of
one source. It:

1. writes all retained payload in that prefix to the other tier;
2. flushes the new payload;
3. atomically publishes one pointer-set commit; and
4. only then reclaims the selected source prefix.

An epoch with retained payload `z` is legal iff the destination has at least
`z` free units before source reclamation. Its modeled physical write cost is

```text
c(z) = q ceil(z/q) + mu,
```

where the rounded term is zero when `z=0`, `q>=1` is a write-traffic
quantum, and `mu>=0` is the durable commit cost. Payload occupancy is `z`,
not the rounded traffic `q ceil(z/q)`. Metadata storage capacity is
provisioned separately; `mu` charges traffic, not payload arena occupancy.

A state `(i,j)` records processed prefix lengths. Define occupied and live
prefix sums `B_s(k)` and `L_s(k)`, both zero at `k=0`.

## 2. Prefix accounting

**Lemma 1 (free-space identity).** At state `(i,j)`,

```text
F_0(i,j) = f_0 + B_0(i) - L_1(j),
F_1(i,j) = f_1 + B_1(j) - L_0(i).                 (1)
```

**Proof.** Initially the identities are immediate. A tier-0 epoch from `i` to
`i'` consumes `L_0(i')-L_0(i)` units in tier 1 and, after commit, releases
`B_0(i')-B_0(i)` units in tier 0. These are exactly the changes in (1). The
tier-1 case is symmetric. Induction over committed epochs proves the result.
`EpochInstance.free_at` computes (1), while `replay` updates free space
incrementally and asserts equality at the end. QED.

Final fit, `F_0(n_0,n_1)>=0` and `F_1(n_0,n_1)>=0`, is necessary but not
sufficient. A destination can be too full for either first output even when the
fully reclaimed final arrangement fits.

## 3. Refinement and legal-step confluence

For reasoning only, refine an epoch into single-segment actions of the same
source. If the whole epoch is legal, each action in the refinement is legal:
the cumulative destination consumption of every refined prefix is no larger
than the epoch's total retained payload. Refinement preserves the final state,
although it generally changes physical cost.

**Lemma 2 (opposite-action swap).** Suppose a legal single-segment schedule
executes a source-`1-s` action followed by a source-`s` action. If the source-`s`
action was already legal before the pair, swapping the pair preserves legality
and reaches the same state.

**Proof.** The moved source-`s` action is legal by premise. It reclaims positive
space in tier `s`, the destination needed by the delayed source-`1-s` action,
so that delayed action remains legal. Prefix order within each source is
unchanged, and the additive updates in (1) commute. QED.

**Theorem 3 (legal-step confluence).** From any completable state, every legal
prefix epoch leads to another completable state.

**Proof.** Let `E` be an arbitrary legal epoch from source `s`, and let `P` be
any complete schedule from the current state. Refine both into single-segment
actions. The source-`s` actions belonging to `E` occur in `P` in source prefix
order. Bubble the first selected action left across intervening opposite-source
actions, then the second, and so on. Before each selected action, the already
moved source-`s` prefix has consumed no more than the corresponding prefix of
`E`; because all live sizes are non-negative and the whole `E` fit initially,
the action is legal. Each adjacent exchange is therefore justified by Lemma 2.
The transformed completion starts with the refined `E`. Merge those actions
back into the original epoch. The suffix is a legal completion after `E`. QED.

**Corollary 4 (safe work conservation).** If a completion exists, every policy
that repeatedly chooses any legal prefix completes. A nonterminal state with
no legal prefix is infeasible.

The result depends on two ordered sources, opposite destinations, frozen
retention, and copy--flush--commit--reclaim. It is not claimed for arbitrary
run selection, three-tier cycles, early subextent reclamation, or changing live
sets.

## 4. Linear feasibility and blocking certificates

At state `(i,j)`, a non-empty source-0 prefix exists iff the first unprocessed
source-0 segment fits in `F_1(i,j)`: every longer prefix contains that segment
and adds non-negative live payload. The same holds symmetrically.

**Theorem 5 (linear feasibility test).** Start at `(0,0)`. Repeatedly process
one first unprocessed segment from any source whose live size fits in the other
tier. If the process reaches `(n_0,n_1)`, the instance is feasible. If neither
first segment fits at a nonterminal state, the instance is infeasible. The
decision uses `O(n_0+n_1)` time and `O(1)` working space beyond the input and
output certificate.

**Proof.** Every selected segment is a legal prefix, so Theorem 3 preserves
completion whenever one exists. If neither first segment fits, no non-empty
prefix from either source can fit; Corollary 4 gives infeasibility. Each step
consumes one segment. QED.

`scan_feasibility` prefers source 0 on ties but does not call an optimizer. A
positive certificate is its source-bit schedule; `replay` checks every guard
and the terminal state. A negative certificate contains `(i,j)`, `(F_0,F_1)`,
and the two next live sizes. For every non-exhausted source, the next live size
must exceed the opposite free component. Zero-live segments are always legal
and can release space needed by the other tier.

## 5. Cost normal form

The rounded payload term is subadditive:

```text
q ceil(a/q) + q ceil(b/q) >= q ceil((a+b)/q).
```

**Lemma 6 (adjacent same-source merge).** Two consecutive epochs from the same
source can be merged into one legal epoch with the same final state and no
larger cost.

**Proof.** Let their live payloads be `a` and `b`. No opposite-source action
occurs between them, so the target free space before the first epoch must be at
least `a+b`: the first consumes `a`, and the second is legal with the remaining
space. The merged source prefix reaches the same state. Subadditivity of the
rounded term and replacement of two commit costs by one prove the cost bound.
QED.

**Corollary 7 (alternating normal form).** Some minimum-cost complete schedule
alternates source tiers. Adjacent epochs from the same source are unnecessary.

## 6. Exact dynamic program

Let `D_s(i,j)` be the minimum cost of reaching `(i,j)` when the last real epoch
used source `s`. Initialize `D_0(0,0)=D_1(0,0)=0` and every other entry to
infinity. For `i'< = n_0` and `j'<=n_1`,

```text
D_0(i',j) = min_{i<i', L_0(i')-L_0(i) <= F_1(i,j)}
              D_1(i,j) + c(L_0(i')-L_0(i)),

D_1(i,j') = min_{j<j', L_1(j')-L_1(j) <= F_0(i,j)}
              D_0(i,j) + c(L_1(j')-L_1(j)).       (2)
```

The optimum is `min_s D_s(n_0,n_1)`.

**Theorem 8 (exact optimizer).** Recurrence (2) computes minimum modeled
physical migration cost in `O((n_0+1)(n_1+1)(n_0+n_1+1))` arithmetic
operations and `O((n_0+1)(n_1+1))` words, including empty tiers.

**Proof.** Corollary 7 guarantees that an optimum appears in the alternating
transition graph. Every graph path is a legal schedule because each edge tests
the destination guard, and its additive edge cost equals replay cost. The graph
is acyclic because each edge increases `i+j`; shortest-path optimality gives the
minimum. There are a constant number of last-source states at each of
`(n_0+1)(n_1+1)` prefix pairs and at most `n_0+n_1` candidate endpoints. QED.

The implementation keeps predecessor pointers and deterministic tie-breaking,
then replays every returned schedule. An unrestricted shortest path permits
adjacent same-source epochs; a no-memo recursion enumerates all legal schedules
on selected tiny instances. Their agreement is a finite implementation check,
not the proof above.

## 7. Per-source lower bound and two-epoch basin

Let `L_s=L_s(n_s)`. Every complete schedule uses at least one epoch for each
nonempty source, and repeated subadditivity gives

```text
LB = sum over nonempty s of [q ceil(L_s/q) + mu].  (3)
```

**Lemma 9.** Equation (3) lower-bounds every complete schedule.

**Theorem 10 (two-epoch basin, `mu>0`).** Suppose both tiers are nonempty and
final fit holds. The lower bound is attained iff

```text
f_1 >= L_0    or    f_0 >= L_1.                   (4)
```

**Proof.** If `f_1>=L_0`, all of source 0 fits in one epoch. After its source is
reclaimed, final fit implies `f_0+B_0-L_1>=0`, so all of source 1 fits; the
reverse order is symmetric. Conversely, splitting a source cannot reduce the
sum of rounded payloads below its rounded total and, because `mu>0`, every
extra epoch adds strictly positive cost. Equality with (3) therefore requires
one epoch per nonempty source. The first whole source must initially fit, which
is exactly one inequality in (4). QED.

When `mu=0`, (4) remains sufficient but is not necessary because split rounded
payloads can tie the one-batch rounded total.

## 8. Reserve dominance and inverse planning

**Proposition 11 (reserve dominance).** If reserve vector `f` is feasible,
every componentwise larger `f'` is feasible, and `OPT(f')<=OPT(f)`.

**Proof.** Equation (1) differs by the fixed non-negative vector `f'-f` at
every prefix state. The same schedule remains legal with unchanged cost. QED.

Thus feasible vectors and every cost sublevel set are upward-closed; their
minimal elements form antichains. Total free space alone is not sufficient:
`(2,0)`, `(1,1)`, and `(0,2)` can have different status despite equal sum.
Final fit gives only

```text
f_0 >= max(0,L_1-B_0),   f_1 >= max(0,L_0-B_1).
```

For an integer total budget `R`, enumerating all `R+1` splits and applying the
DP returns the best direction-sensitive allocation in
`O((R+1)(n_0+1)(n_1+1)(n_0+n_1+1))` arithmetic operations,
including zero budget and empty tiers. This is enumeration in the numeric
budget, not polynomial time in its bit length. For a write budget `C`, existence of a split
with total reserve at most `R` and cost at most `C` is monotone in `R`, so a
bounded search yields exact inverse reserve.

## 9. Exact unit-exchange frontier

For positive integers `n,r` with `1<=r<=n`, put `n` all-live unit segments in
each tier, start with reserve `(r,r)`, and set `q>=2r`.
Let `d=i-j`. Equation (1) becomes

```text
F_0=r+d,    F_1=r-d.                              (5)
```

A source-0 epoch is an increasing run of `d`; a source-1 epoch is a decreasing
run. Legality confines `d` to `[-r,r]`. Processing all segments requires total
upward variation `n` and downward variation `n`, hence total variation `2n`.
For `k` alternating runs, the first and last have length at most `r` and every
interior run at most `2r`, so total variation is at most `2r(k-1)`. Therefore
`k>=ceil(n/r)+1`.

**Theorem 12 (unit-exchange frontier).** The minimum number of epochs is

```text
k*(n,r) = ceil(n/r)+1.                            (6)
```

Because every epoch copies at most `2r<=q` live units,

```text
C*(n,r) = (ceil(n/r)+1)(q+mu),
WA_phys/live = C*(n,r)/(2n).                      (7)
```

**Construction.** Write `n=ar+t`, `0<=t<r`.

- If `t=0`, start with a run of length `r`, alternate full runs of length `2r`
  between the two boundaries, and finish with a run of length `r` back to
  zero. There are `a+1=ceil(n/r)+1` runs, and each direction contributes
  exactly `ar=n`.
- If `t>0`, begin with an increasing run of length `t`, then a decreasing run
  of length `r+t` to reach `-r`. Continue bouncing between boundaries with
  full `2r` runs and finish with a length-`r` return to zero. The remaining
  `a` runs contribute the required multiples of `r`; direct summation gives
  `ar+t=n` in each direction. The number of runs is
  `a+2=ceil(n/r)+1`.

The construction meets the variation lower bound. Equation (5) bounds every
run by `2r`, so each nonempty epoch rounds to exactly one quantum and costs
`q+mu`, proving (7). QED.

## 10. Abstract recovery invariant

For every retained token, durable metadata initially selects a durable old
copy. Writing or flushing the new copy leaves that selection unchanged. The
atomic pointer-set commit occurs only after every new token is durable and
switches all selected pointers together. Source reclaim occurs only after the
commit. Therefore, before commit the selected old copy exists, and after
commit the selected new copy exists. Induction over events and epochs proves
that every retained token resolves at every modeled crash prefix.

`src/epoch_recovery.py` enumerates payload-write, flush, commit, and reclaim
events and crashes after each. Four negative controls violate distinct
premises: publish before flush, reclaim before commit, omit one retained token
from the persisted payload before an otherwise atomic pointer commit, and torn
commit followed by reclaim. Detection means
at least one crash prefix in each executed mutated run fails the recovery
predicate: every selected extent must be durable, and the recovered tokens
must equal the retained set without duplication. The three ordering mutations
can therefore fail on all-dead schedules through an unresolved metadata pointer,
not retained-token loss. Persisted-payload truncation is skipped on the eight
all-dead schedules because no retained token exists to truncate. This is not a
device model: it excludes torn sectors, controller caches,
filesystem reorderings below the flush interface, checksums, allocator replay,
and real power cuts.

## 11. Finite implementation checks

The retained campaign covers 254,016 ordered instances. The alternating DP and
unrestricted DP agree on status and cost in every case. The linear scan agrees
on feasibility in every case. A no-memo recursion agrees on all 5,184 patterns
at the maximal reserve corner `(6,6)`, all with `OPT=LB`; this is not a
minimal-reserve frontier check. A backward viability computation counts 1,490,305
nonterminal viable prefix-state instances and audits 2,953,804 legal outgoing
edges; none leaves viability. Terminal states have no outgoing edges and are
excluded from the count. The unit-exchange formula agrees with the DP on 64
`(n,r)` points. These checks
attack implementation mistakes and finite counterexamples; the general claims
rest on the proofs above.

## 12. Boundary and non-claims

`proofs/unordered-boundary.md` treats a different model in which any remaining
run may be selected. That model admits legal-choice deadlocks and a direct
3-PARTITION reduction. It is retained only to show that oldest-prefix order is
substantive; its constant one-copy payload objective was rejected as the core
write-optimization model.

The recovery-epoch results do not claim cache hit-rate improvement, request
latency, SSD lifetime, device write amplification, production crash safety, or
optimal online admission/eviction. Public trace excerpts validate parsers,
version liveness, segmentation, and certificate replay only.
