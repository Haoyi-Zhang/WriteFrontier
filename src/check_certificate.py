"""Independent implementation of finite certificate checking, not independent authorship.
Only standard library; intentionally imports neither the planner nor its state model.
"""
import json,sys
from pathlib import Path

class InvalidCertificate(ValueError):pass

def check(c):
    def need(condition,message):
        if not condition:raise InvalidCertificate(message)
    need(isinstance(c,dict),'certificate must be an object')
    a=c.get('instance',{})
    need(isinstance(a,dict),'instance must be an object')
    rs=a.get('runs'); free=a.get('free')
    need(isinstance(rs,list) and len(rs)<=22,'run list/size')
    need(isinstance(free,list) and len(free)==2,'free list')
    need(all(type(x) is int and 0<=x<2**63 for x in free),'free integer range')
    for r in rs:
        need(isinstance(r,dict),'run must be an object')
        need(type(r.get('source')) is int and r['source'] in (0,1),'source')
        need(type(r.get('occupied')) is int and type(r.get('live')) is int,'size integer')
        need(0<r['live']<=r['occupied']<2**63,'size bounds')
    # Occupancy is recomputed from untouched originals and completed outputs.
    cap=[free[t]+sum(r['occupied'] for r in rs if r['source']==t) for t in (0,1)]
    full=(1<<len(rs))-1
    def usage(mask):
        used=[0,0]
        for i,r in enumerate(rs):
            if mask&(1<<i):used[1-r['source']]+=r['live']
            else:used[r['source']]+=r['occupied']
        return used
    kind=c.get('kind')
    if kind=='final-deficit':
        need(any(x>y for x,y in zip(usage(full),cap)),'no final deficit exists')
        return {'valid':True,'kind':kind,'checked_states':1}
    if kind=='order':
        order=c.get('order');need(isinstance(order,list),'order list')
        need(len(order)==len(rs) and all(type(x) is int for x in order),'order size/type')
        need(set(order)==set(range(len(rs))),'order not a permutation')
        mask=0
        for i in order:
            used=usage(mask);d=1-rs[i]['source']
            need(used[d]+rs[i]['live']<=cap[d],f'copy exceeds capacity at run {i}')
            mask|=1<<i
        return {'valid':True,'kind':kind,'checked_states':len(order)+1}
    need(kind=='closed-set','unknown certificate kind')
    masks=c.get('closed_masks');need(isinstance(masks,list) and len(masks)<=1048576,'mask list/size')
    need(all(type(m) is int and 0<=m<=full for m in masks),'mask range')
    S=set(masks);need(len(S)==len(masks),'duplicate mask')
    need(0 in S and full not in S,'missing initial state or contains goal')
    for mask in S:
        used=usage(mask)
        need(all(x<=y for x,y in zip(used,cap)),'overcapacity certificate state')
        for i,r in enumerate(rs):
            if mask&(1<<i):continue
            d=1-r['source']
            if used[d]+r['live']<=cap[d]:
                need((mask|(1<<i)) in S,f'not transition-closed: {mask}, run {i}')
    return {'valid':True,'kind':kind,'checked_states':len(S)}

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('usage: python src/check_certificate.py CERTIFICATE.json')
    p=Path(sys.argv[1])
    if p.stat().st_size>64*1024*1024:raise SystemExit('certificate exceeds 64 MiB parsing bound')
    try: print(json.dumps(check(json.loads(p.read_text())),sort_keys=True))
    except (ValueError,KeyError,TypeError) as exc:raise SystemExit(f'INVALID: {exc}')
