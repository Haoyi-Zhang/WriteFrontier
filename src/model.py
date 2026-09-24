"""Finite copy-before-reclaim migration model. Integer units; no device emulation."""
from dataclasses import dataclass
from typing import Iterable

@dataclass(frozen=True)
class Run:
    source: int
    occupied: int
    live: int
    def __post_init__(self):
        if type(self.source) is not int or self.source not in (0,1):
            raise ValueError('source must be 0 or 1')
        if type(self.live) is not int or type(self.occupied) is not int:
            raise ValueError('sizes must be integer units')
        if not 0 < self.live <= self.occupied:
            raise ValueError('require 0 < live <= occupied')
    @property
    def target(self):
        return 1-self.source

@dataclass(frozen=True)
class Episode:
    runs: tuple[Run,...]
    free: tuple[int,int]
    def __post_init__(self):
        if len(self.free)!=2 or any(type(x) is not int or x<0 for x in self.free):
            raise ValueError('two nonnegative integer free-space values required')
    def final_free(self):
        f=list(self.free)
        for r in self.runs:
            f[r.source]+=r.occupied
            f[r.target]-=r.live
        return tuple(f)
    def final_fits(self):
        return min(self.final_free())>=0

def balances(e:Episode, mask:int):
    f=list(e.free)
    for i,r in enumerate(e.runs):
        if mask>>i&1:
            f[r.source]+=r.occupied; f[r.target]-=r.live
    return tuple(f)

def replay(e:Episode,order:Iterable[int]):
    """Check every capacity prefix, not only the final state."""
    f=list(e.free); seen=set(); events=[]
    for j in order:
        if type(j) is not int or not 0<=j<len(e.runs) or j in seen:
            raise ValueError('invalid or repeated run')
        r=e.runs[j]
        if f[r.target]<r.live:
            raise ValueError(f'capacity witness: run={j}, target={r.target}, need={r.live}, free={f[r.target]}')
        before=tuple(f)
        # The shadow output coexists with the unreclaimed source until publication.
        f[r.target]-=r.live
        shadow=tuple(f)
        f[r.source]+=r.occupied
        seen.add(j)
        events.append({'run':j,'before':before,'shadow':shadow,'after':tuple(f)})
    return {'complete':len(seen)==len(e.runs),'free':tuple(f),'events':events,
            'payload_units':sum(e.runs[j].live for j in seen)}

def guarded_order(e:Episode,priority:str='fifo'):
    """Work-conserving heuristic. Refuses a blocked plan; no optimality claim."""
    remaining=set(range(len(e.runs))); f=list(e.free); order=[]
    while remaining:
        enabled=[i for i in remaining if f[e.runs[i].target]>=e.runs[i].live]
        if not enabled: return order
        if priority=='fifo': key=lambda i:(i,)
        elif priority=='small': key=lambda i:(e.runs[i].live,i)
        elif priority=='large': key=lambda i:(-e.runs[i].live,i)
        elif priority=='garbage': key=lambda i:(-(e.runs[i].occupied-e.runs[i].live),i)
        else: raise ValueError('unknown priority')
        j=min(enabled,key=key); r=e.runs[j]
        f[r.target]-=r.live; f[r.source]+=r.occupied
        remaining.remove(j); order.append(j)
    return order

def universal_guard(e:Episode):
    """Sufficient, not necessary; both migration directions must be present."""
    caps=[max((r.live for r in e.runs if r.target==t),default=0) for t in (0,1)]
    if not all(caps): return e.final_fits()
    return e.final_fits() and sum(e.free)>=sum(caps)-1
