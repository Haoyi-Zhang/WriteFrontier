#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import subprocess,sys,json,csv,hashlib,re
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent

def run(cmd,timeout=3600):
    p=subprocess.run(cmd,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=timeout)
    return p.returncode,p.stdout
checks={};details={}
rc,out=run([sys.executable,'-m','compileall','-q','.'],600);checks['compileall']=rc==0
rc,out=run([sys.executable,'-m','unittest','discover','-s','tests','-v'],3600);checks['unit_tests']=rc==0;details['unit_test_tail']=out[-2000:]
if (ROOT/'verify_revision.py').exists():
    rc,out=run([sys.executable,'verify_revision.py','--root','.'],3600);checks['verify_revision']=rc==0;details['verify_revision_tail']=out[-2000:]
rob=json.loads((HERE/'robustness-summary.json').read_text());checks['robustness_evidence']=rob.get('normalized_observations',0)>0 and len(rob.get('policies',[]))>=2;details['robustness_observations']=rob.get('normalized_observations');details['policies']=rob.get('policies')
rows=list(csv.DictReader((HERE/'reference-audit-final.csv').open(encoding='utf-8-sig')));bad=[x for x in rows if x.get('status') in {'unresolved','metadata_mismatch','url_error','invalid_isbn'}];checks['frozen_reference_audit']=len(rows)>=40 and not bad and all(int(x.get('citation_context_count') or 0)>0 for x in rows);details['reference_rows']=len(rows);details['bad_reference_rows']=bad
# Check release manifest
man=ROOT/'RELEASE-MANIFEST.sha256';missing=[];mismatch=[]
if man.exists():
    for line in man.read_text().splitlines():
        if not line.strip():continue
        h,rel=line.split('  ',1);p=ROOT/rel
        if not p.exists():missing.append(rel)
        elif hashlib.sha256(p.read_bytes()).hexdigest()!=h:mismatch.append(rel)
checks['release_manifest']=man.exists() and not missing and not mismatch;details['manifest_missing']=missing;details['manifest_mismatch']=mismatch
res={'checks':checks,'details':details,'passed':all(checks.values())};print(json.dumps(res,indent=2,ensure_ascii=False))
if not res['passed']:sys.exit(2)
