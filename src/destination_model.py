"""Small raw-tuple FIFO reachability checker for fixed destination routing.

No device operations, project optimizer, or two-tier capacity code are used.
Each source has one fixed destination distinct from itself. Outputs are never
recopied. This is a boundary model, not a multi-tier storage implementation.
"""
from functools import lru_cache
from itertools import product


def audit_destinations(tiers, destinations, initial_free):
    count = len(tiers)
    if count < 2 or len(destinations) != count or len(initial_free) != count:
        raise ValueError("inconsistent tier, route, and reserve lengths")
    for source, destination in enumerate(destinations):
        if type(destination) is not int or not 0 <= destination < count or destination == source:
            raise ValueError("each destination must be a different valid tier")
    if any(type(f) is not int or f < 0 for f in initial_free):
        raise ValueError("reserve must be non-negative integer")
    for tier in tiers:
        for b, l in tier:
            if type(b) is not int or type(l) is not int or not 0 <= l <= b or b <= 0:
                raise ValueError("invalid raw occupied/live pair")
    terminal = tuple(len(t) for t in tiers)

    def free_at(indices):
        free = list(initial_free)
        for source, end in enumerate(indices):
            for occupied, live in tiers[source][:end]:
                free[source] += occupied
                free[destinations[source]] -= live
        return tuple(free)

    def successors(indices):
        free = free_at(indices)
        if min(free) < 0:
            return
        for source, tier in enumerate(tiers):
            live = 0
            for end in range(indices[source] + 1, len(tier) + 1):
                live += tier[end - 1][1]
                if live > free[destinations[source]]:
                    break
                following = list(indices)
                following[source] = end
                yield (source, indices[source], end), tuple(following)

    @lru_cache(None)
    def viable(indices):
        if min(free_at(indices)) < 0:
            return False
        if indices == terminal:
            return True
        return any(viable(nxt) for _, nxt in successors(indices))

    origin = (0,) * count
    violations = []
    edges = states = 0
    for indices in product(*(range(n + 1) for n in terminal)):
        if indices == terminal or not viable(indices):
            continue
        states += 1
        for batch, nxt in successors(indices):
            edges += 1
            if not viable(nxt):
                violations.append({"state": list(indices), "free": list(free_at(indices)),
                                   "batch": list(batch), "successor": list(nxt),
                                   "successor_free": list(free_at(nxt))})
    path = []
    indices = origin
    if viable(origin):
        while indices != terminal:
            batch, indices = next((b, nxt) for b, nxt in successors(indices) if viable(nxt))
            path.append(list(batch))
    return {"initial_feasible": viable(origin), "final_free": list(free_at(terminal)),
            "viable_nonterminal_states": states, "legal_edges": edges,
            "violations": violations, "completion": path}
