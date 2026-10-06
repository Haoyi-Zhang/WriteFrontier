# Fixed-retention relocation episodes

These are handwritten mathematical arguments, accompanied by finite executable
checks. They are not proof-assistant-checked theorems. The classical relationships
in the last section are essential limitations on novelty.

## 1. Definitions and capacity identity

There are two independently bounded arenas, indexed 0 and 1. Initial free space
is a nonnegative integer vector f. Each original run j has source s_j, destination
d_j=1-s_j, occupied size b_j and retained live size l_j, with 1 <= l_j <= b_j.
The original runs do not overlap. Live identities are disjoint and immutable.
All original runs have predetermined destinations and must be processed exactly
once. No output is subsequently deleted, overwritten, deduplicated or moved.
No other requests or third-party resource consumers occur during the episode.
Allocation is ideally packable: only total occupancy in each arena matters.
The physical reclaim unit is the whole original run, irrespective of the output
write granularity. A distinct metadata arena is reserved separately.

For a set S of completed runs define

    f_t(S) = f_t(0) + sum_{j in S, s_j=t} b_j
                       - sum_{j in S, d_j=t} l_j.                 (1)

This identity follows by induction on completed runs. It is a bookkeeping
identity even for an unreachable S; it is not a reachability certificate.
To execute j not in S, its entire output must coexist with its unreclaimed
source. Thus a whole-run transition is legal exactly when f_{d_j}(S) >= l_j.
Copying decreases the destination by l_j; after persistence and publication,
reclaiming increases the source by b_j. Source and destination differ. These
operations cannot make a previously nonnegative coordinate negative when the
guard holds. Final fit means both coordinates in (1) for S=all runs are >=0.

For fixed output byte size U per allocation unit, every completed one-copy order
writes U*sum_j l_j payload bytes. If each run publication writes m metadata
bytes, its modeled metadata cost is n*m. Neither term varies with the order.
There are no application writes during the episode, so this sum is not a
measured application-relative write-amplification factor. The model supports a
feasibility frontier, not a nontrivial write-cost optimum over completed orders.

## 2. Two counterexamples

Blocked exchange: j=0 has (s,b,l)=(0,2,2), j=1 has (1,2,2), and f=(1,1).
Equation (1) gives final free space (1,1), but neither initial transition is
legal. For these same jobs, f=(0,2) permits order (0,1); f=(2,0) permits (1,0).
All three configurations have total free space 2. Hence final fit and total
reserve alone do not decide individual-episode reachability. The exact
componentwise-minimal feasible reserve vectors are (0,2) and (2,0): zero total
reserve or only one unit cannot execute any job, and any legal first job
requires at least two units in its destination.

Order-sensitive exchange: jobs A=(0,1,1), B=(1,1,1), C=(0,2,2), D=(1,2,2),
f=(1,1). A then B leaves the same reserve with only C and D remaining, so the
legal prefix (A,B) is stuck. A,D,C,B gives reserve sequence
(1,1), (2,0), (0,2), (2,0), (1,1) and is legal. Its payload is 6 units. The
minimal feasible reserve vectors are (0,2),(1,1),(2,0). The endpoints are feasible
by direct replay. For total reserve <=1, no 2-unit job can ever execute because
all jobs have b=l and preserve total reserve. A feasible vector with total
reserve >=2 dominates one of the three displayed vectors. Thus the frontier is
complete, not merely a bounded search result.

## 3. Completion-order normalization

Proposition. In the defined fixed-output model, permitting arbitrary
interleavings of partial output copies does not enlarge the set of feasible
episodes if no original source capacity is released before that run's entire
retained payload has been copied and published. This proposition also holds for
any finite number of arenas and fixed source/destination assignments.

Proof. Take any successful interleaved execution and list jobs in the order in
which their originals first become reclaimable. Delaying a reclamation cannot
help capacity, so analyze the instant immediately before each release. Let S
be the previously completed jobs, and let j be next. Write p_t for the total
space occupied in arena t by partially copied outputs of all other unfinished
jobs at that instant. These values are nonnegative. The actual free vector
immediately before releasing j is

    f(S) - l_j e_{d_j} - p.

It is nonnegative. Consequently f_{d_j}(S) >= l_j. By induction, after executing
the jobs of S serially in the same completion order, the serial arena state has
free vector f(S), so copying j is legal. Releasing its original produces the
serial state f(S union {j}). Applying this argument to every completion gives
a legal whole-run order with the identical retained output and payload cost.
Conversely, a legal whole-run order is a special case of partial copying. QED.

The argument does not suppose that publication is monolithic. Smaller durable
output publications still leave p nonnegative if they release no physical
source capacity. The assumptions fail when source subextents can be reclaimed
early, outputs can be discarded or recopied, retention changes, or overlapping
sources share physical bytes. No claim is made for those models. The unit-chunk
oracle implements whole-source release on completion, not independent source
block erasure. In the blocked exchange, writing a one-unit partial output into
each tier consumes both reserves without releasing either original.

## 4. A worst-case reserve guard

Let L_t be the largest original payload destined to arena t. Suppose that both
directions have at least one job and that the final state fits. If

    f_0(0)+f_1(0) >= L_0+L_1-1,                                 (2)

then every work-conserving legal serial order completes. A work-conserving order
always chooses an enabled unfinished job when one exists; it need not be FIFO.
This is an integer-unit bound. It is not a statement about continuous capacities.

Proof. Total free space increases by b_j-l_j >=0 at each completed job. If
unfinished jobs remain in both directions and none is enabled, each destination
has less free space than every unfinished payload arriving there, so
f_t(S) <= L_t-1. Summing contradicts (2). If jobs remain in only one direction,
there will be no more source releases into their common destination t. Final
fit implies

    f_t(S) >= sum_{unfinished j} l_j.

Each such job is enabled; after executing one, the same argument applies to the
rest. Thus no nonterminal deadlock is reachable. Since a legal step completes
one of finitely many jobs, every work-conserving order finishes. QED.

If only one migration direction is present initially, final fit alone suffices
by the second part of the argument. The empty episode also completes.

Tightness of the aggregate guarantee. For any positive integers L_0,L_1, take
one source-0 job with b=l=L_1 and one source-1 job with b=l=L_0. Set initial
reserve to (L_0-1,L_1-1). The final reserve is (L_1-1,L_0-1), which fits, but
neither job is initially enabled. Total reserve is exactly L_0+L_1-2. Thus a
universal guarantee based on these maxima and final fit cannot lower (2) by an
integer unit. This does not make the guard necessary for each instance; the
four-job example completes with total reserve 2 although (2) requires 3.

## 5. Relation to bounded stock size and 3-PARTITION

In the all-live case b_j=l_j, total free capacity F is invariant. Tracking just
x=f_0 gives a signed-prefix problem: a source-0 move adds l_j to x and a
source-1 move subtracts l_j, with x required to remain in [0,F]. For addition,
the destination guard is F-x >= l_j; for subtraction it is x >= l_j. Thus these
conditions are exactly the interval constraints on the new prefix. When the
directional totals balance and x starts at zero, this is the decision form of
the classical stock-size problem. The resemblance is mathematical, not merely
an implementation analogy.

A direct reduction makes the ordering difficulty explicit. Given positive
integers a_1,...,a_{3m} with B/4 < a_i < B/2 and sum a_i=mB, create one source-0
all-live run of size a_i for each item, m source-1 all-live runs of size B, and
initial free vector (0,B). The final vector is also (0,B). A B-sized reverse
run can execute only when f_0=B. Between consecutive reverse runs, forward
runs must therefore have total size exactly B, as any larger prefix would
violate f_1>=0. The strict item bounds imply exactly three forward runs in
each such group. All jobs complete only if the item indices partition into
triples of sum B. Conversely, execute each such triple and then one reverse
run to obtain a legal complete order. The transformation is linear in the
number of items and preserves the magnitude of the numerical input.

This establishes an exact reduction from 3-PARTITION to the model's feasibility
problem; it is not offered as a new complexity result for resource scheduling.
An order is checked in polynomial time in the input bit length. The executable
306-instance comparison is a finite check of the reduction implementation, not
a substitute for this general equivalence proof. The stock-size discussion in
Newman, Roeglin and Seif is a direct novelty adversary: Section 1 of the
ESA 2016 paper defines stock-size prefix feasibility, while Appendix A of
the [full version](https://arxiv.org/abs/1511.09259) gives the alternating
stock-size hardness reduction. That appendix is not in the 16-page
conference version.

## 6. Finite certificate soundness

An order certificate embeds the complete instance and a permutation of its jobs.
The checker reconstructs capacity from original occupancy and initial free
space. For each prefix S it sums untouched originals and completed outputs,
then checks that the next shadow output fits before the source is removed.
Induction gives a feasible path from empty to full S.

For infeasibility, a final-deficit certificate is sufficient if the recomputed
final occupancy exceeds capacity. Otherwise a certificate gives a set C of
subsets, represented as integer masks. The checker requires the empty set in
C, the full set absent, nonnegative capacity in every listed state, and every
legal successor of every listed state to belong to C. By induction on path
length, all states reachable from the empty set belong to C. A full execution
would reach the excluded full set, a contradiction. C need not contain only
reachable states; transition closure, not minimality, supplies soundness.
The producer uses the reachable set. Budget exhaustion is UNKNOWN.

The checker uses occupancy reconstruction and imports neither planner nor
transition model. Input validation rejects booleans where integer identifiers
or sizes are required. A certificate proves only its embedded instance. It does
not authenticate a trace, establish provenance, or prove the producer bug-free.
Finite cross-checking and implementation diversity do not constitute an
independently authored review or proof-assistant verification.

## 7. Abstract crash invariant

At the start of a run move, its durable pointer references a durable original
containing all its retained identities and values. Volatile output copying
leaves that pointer and original intact. Flushing the output also leaves the
old recovery route intact. Atomic publication changes the pointer only after
the full new output is durable. Reclaiming the old source therefore cannot
remove the pointed-to retained values. Distinct jobs have disjoint identities
and separate pointers, so the induction composes across a serial order.
At a crash, volatile copies disappear and only durable pointer targets are
read. Thus all pinned identities and values survive every specified transition
boundary under these assumptions.

The finite recovery model tests the initial state, every output-unit copy,
flush, publication and reclaim. It injects four separately named erroneous
protocols: early reclaim; publication before flush; truncating the flushed
output; and assigning another run's pointer (when n>=2). The reported failures
are bad retained-value recoveries in these toy protocols, not exploits or
observations of any actual storage implementation. The model assumes atomic
pointer persistence and completed operations. It does not model torn records,
flush reordering, corruption, concurrent modification, reclamation replay after
restart, physical addresses or real device power failure. Correct crash-prefix
reads therefore do not establish a crash-restartable cache implementation.

## 8. Consequence for the research question

Bender et al.'s checkpointed reallocation model already retains old and new
copies until durable mapping updates and accounts for largest-object temporary
space. Classical stock-size bounds already expose the signed-prefix ordering
structure. The results above identify an important missing feasibility guard
in a candidate byte-accounting model, but do not establish a new write-cost
frontier for a cache. A variable live-set, destination, re-copy, reclamation-unit
or admission choice would be required to make successful schedules have
meaningfully different write costs. Such an extension must carry its own
retention/recovery semantics and evidence; it is not silently assumed here.
