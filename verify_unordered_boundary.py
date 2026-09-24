#!/usr/bin/env python3
"""Compare deterministic scientific outputs; runtime is deliberately excluded."""
import argparse,csv,json
from pathlib import Path

def verify(a:Path,b:Path):
    names=[f'oracle-{i:02d}.csv' for i in range(8)]
    names += ['boundary.csv','reduction.json','examples.json','frontiers.csv',
              'recovery_summary.json','crash_example.json','summary.json']
    names += [str(p.relative_to(a)) for p in sorted((a/'certificates').glob('*.json'))]
    if len(names)!=20:raise ValueError('expected five certificates and 15 other scientific outputs')
    for name in names:
        if not (a/name).is_file() or not (b/name).is_file():raise ValueError('missing output: '+name)
        if (a/name).read_bytes()!=(b/name).read_bytes():raise ValueError('scientific mismatch: '+name)
    summary=json.loads((b/'summary.json').read_text())
    if not summary.get('complete_exhaustive_grid') or summary.get('cases')!=65484:
        raise ValueError('grid incomplete')
    seen=[]
    for i in range(8):
        with (b/f'oracle-{i:02d}.csv').open() as f:seen.extend(int(r['case']) for r in csv.DictReader(f))
    if seen!=list(range(65484)):raise ValueError('raw case indices incomplete or reordered')
    print(json.dumps({'scientific_files_identical':len(names),'grid_instances':len(seen),
                      'runtime_compared':False},sort_keys=True))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('reference',type=Path);p.add_argument('reproduced',type=Path)
    a=p.parse_args();verify(a.reference,a.reproduced)
