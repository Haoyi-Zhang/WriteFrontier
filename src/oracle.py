"""Exact finite oracles; state bounds are explicit and failures never mean infeasible."""
from functools import lru_cache
from itertools import permutations
from model import Episode

class BudgetExceeded(RuntimeError): pass

def exact_order(e:Episode,max_states:int=1048576):
    n=len(e.runs)
    if n>22: raise BudgetExceeded('at most 22 jobs admitted by this implementation')
    count=0; full=(1<<n)-1
    @lru_cache(None)
    def visit(mask,f0,f1):
        nonlocal count
        count+=1
        if count>max_states: raise BudgetExceeded('state budget reached; outcome unknown')
        if mask==full: return ()
        for j,r in enumerate(e.runs):
            if mask>>j&1: continue
            f=[f0,f1]
            if f[r.target]<r.live: continue
            f[r.target]-=r.live; f[r.source]+=r.occupied
            suffix=visit(mask|1<<j,*f)
            if suffix is not None: return (j,)+suffix
        return None
    if not e.final_fits(): return {'order':None,'states':0,'status':'infeasible-final'}
    order=visit(0,*e.free)
    return {'order':order,'states':count,'status':'feasible' if order is not None else 'infeasible'}

def permutation_oracle(e:Episode):
    """Separately coded factorial checker for small input cross-checks."""
    if len(e.runs)>8: raise BudgetExceeded('permutation oracle limited to eight jobs')
    count=0
    for perm in permutations(range(len(e.runs))):
        count+=1
        occupied=[sum(r.occupied for r in e.runs if r.source==t) for t in (0,1)]
        capacity=[occupied[t]+e.free[t] for t in (0,1)]
        ok=True
        for j in perm:
            r=e.runs[j]
            if occupied[1-r.source]+r.live>capacity[1-r.source]:
                ok=False;break
            occupied[1-r.source]+=r.live
            occupied[r.source]-=r.occupied
        if ok:return perm,count
    return None,count

def any_deadlock(e:Episode,max_states:int=1048576):
    """Enumerate all reachable masks, returning an actual nonterminal deadlock."""
    stack=[(0,*e.free,())]; seen=set(); full=(1<<len(e.runs))-1
    while stack:
        mask,f0,f1,path=stack.pop()
        if mask in seen:continue
        seen.add(mask)
        if len(seen)>max_states:raise BudgetExceeded('all-order state budget')
        if mask==full:continue
        enabled=[]
        for j,r in enumerate(e.runs):
            if not(mask>>j&1) and (f0,f1)[r.target]>=r.live:
                f=[f0,f1]; f[r.target]-=r.live; f[r.source]+=r.occupied
                enabled.append((mask|1<<j,*f,path+(j,)))
        if not enabled:return {'path':path,'mask':mask,'free':(f0,f1),'states':len(seen)}
        stack.extend(enabled)
    return None

def chunk_oracle(e:Episode,limit=200000):
    """Unit output chunks; original occupied bytes released only at completion.
    Return feasibility. Exhaustively explores all partial progress vectors.
    No shared transition implementation with the whole-run oracle.
    """
    n=len(e.runs); goals=tuple(r.live for r in e.runs); count=0
    @lru_cache(None)
    def visit(progress):
        nonlocal count
        count+=1
        if count>limit:raise BudgetExceeded('chunk state budget')
        if progress==goals:return True
        usage=[sum(r.occupied for r in e.runs if r.source==t) for t in (0,1)]
        capacity=[usage[t]+e.free[t] for t in (0,1)]
        for i,r in enumerate(e.runs):
            usage[r.target]+=progress[i]
            if progress[i]==r.live:usage[r.source]-=r.occupied
        for j,r in enumerate(e.runs):
            if progress[j]==r.live or usage[r.target]+1>capacity[r.target]:continue
            q=list(progress); q[j]+=1
            if visit(tuple(q)):return True
        return False
    feasible=visit((0,)*n)
    return feasible,count

def reserve_frontier(runs,max_free):
    """Minimal componentwise reserve vectors within an explicitly bounded square."""
    feasible=[]
    for x in range(max_free+1):
        for y in range(max_free+1):
            e=Episode(tuple(runs),(x,y))
            out=exact_order(e)
            if out['order'] is not None:
                feasible.append((x,y));break
    return [p for p in feasible if not any(q!=p and q[0]<=p[0] and q[1]<=p[1] for q in feasible)]
