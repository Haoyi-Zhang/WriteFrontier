"""Witness production. Checker is separate and does not import this module."""
from model import Episode,balances
from oracle import BudgetExceeded

def encode(e):
    return {'runs':[{'source':r.source,'occupied':r.occupied,'live':r.live} for r in e.runs], 'free':list(e.free)}

def infeasible_certificate(e:Episode,limit:int=1048576):
    if not e.final_fits():return {'instance':encode(e),'kind':'final-deficit'}
    full=(1<<len(e.runs))-1; todo=[0]; reached={0}
    while todo:
        mask=todo.pop()
        if mask==full:raise ValueError('instance is feasible; no closed-set certificate')
        f=balances(e,mask)
        for i,r in enumerate(e.runs):
            if not mask>>i&1 and f[r.target]>=r.live:
                successor=mask|1<<i
                if successor not in reached:
                    reached.add(successor);todo.append(successor)
                    if len(reached)>limit:raise BudgetExceeded('certificate budget exceeded')
    return {'instance':encode(e),'kind':'closed-set','closed_masks':sorted(reached)}

def feasible_certificate(e,order):
    return {'instance':encode(e),'kind':'order','order':list(order)}
