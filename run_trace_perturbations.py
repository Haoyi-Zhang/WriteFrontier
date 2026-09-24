from __future__ import annotations
from pathlib import Path
import csv,random,subprocess,sys,json,re,shutil
ART=Path(__file__).resolve().parent; ROOT=ART.parent; W=ART
src=ART/'data'/'trace-derived'/'twitter_segments.csv'; OUT=ART/'results'/'trace-perturbation-reproduced'; OUT.mkdir(exist_ok=True)
rows=list(csv.DictReader(src.open(encoding='utf-8-sig'))); fields=list(rows[0])
low={c.lower():c for c in fields}
source=next((c for c in fields if c.lower() in {'source_bytes','written_bytes','total_bytes','segment_bytes','input_bytes','physical_bytes'}),None)
live=next((c for c in fields if c.lower() in {'live_bytes','retained_bytes','surviving_bytes','valid_bytes'}),None)
order=next((c for c in fields if c.lower() in {'segment','segment_id','segment_index','index','ordinal'}),None)
groups=[c for c in fields if any(t in c.lower() for t in ['cluster','trace','window','workload'])]
if not source or not live:raise SystemExit(f'Cannot identify source/live byte columns: {fields}')

def iv(x):return int(float(x))
def transform(name):
    rr=[dict(r) for r in rows]
    if name=='scale_x2':
        for r in rr:
            r[source]=str(iv(r[source])*2);r[live]=str(iv(r[live])*2)
    elif name=='retention_half':
        for r in rr:r[live]=str(max(0,iv(r[live])//2))
    elif name=='retention_high':
        for r in rr:r[live]=str(min(iv(r[source]),(iv(r[live])*5+3)//4))
    elif name in {'reverse_order','fixed_shuffle'}:
        buckets={}
        for r in rr:buckets.setdefault(tuple(r[g] for g in groups),[]).append(r)
        out=[];rng=random.Random(20260921)
        for key,b in sorted(buckets.items(),key=lambda x:x[0]):
            if name=='reverse_order':b=list(reversed(b))
            else:rng.shuffle(b)
            if order:
                # preserve numeric base but impose new sequence
                vals=[]
                try:vals=sorted(iv(x[order]) for x in b)
                except:vals=list(range(len(b)))
                for i,r in enumerate(b):r[order]=str(vals[i])
            out.extend(b)
        rr=out
    else:raise KeyError(name)
    for r in rr:
        assert 0<=iv(r[live])<=iv(r[source])
    return rr

manifest=[]
for name in ['scale_x2','retention_half','retention_high','reverse_order','fixed_shuffle']:
    d=OUT/name;d.mkdir(exist_ok=True);inp=d/'segments.csv'
    with inp.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(transform(name))
    result=d/'results';
    if result.exists():shutil.rmtree(result)
    p=subprocess.run([sys.executable,'run_trace_study.py','--segments',str(inp),'--out',str(result)],cwd=ART,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=3600)
    (d/'run.log').write_text(p.stdout,encoding='utf-8')
    manifest.append({'variant':name,'input':str(inp),'returncode':p.returncode,'groups':groups,'source_column':source,'live_column':live,'order_column':order})
    if p.returncode:raise SystemExit(f'{name} failed')
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
