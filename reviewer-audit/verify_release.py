#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import csv,json,re,subprocess,sys,shutil,hashlib,tempfile,os
HERE=Path(__file__).resolve().parent
ART=HERE.parent
ROOT=ART.parent
PAPER=ROOT/'paper'

def run(cmd,cwd=None,timeout=3600):
    p=subprocess.run(cmd,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=timeout)
    return p.returncode,p.stdout

def parse_bib_keys(text):
    return re.findall(r'@[A-Za-z]+\s*\{\s*([^,\s]+)\s*,',text)
def citations(text):
    out=[]
    text='\n'.join(re.sub(r'(?<!\\)%.*$','',x) for x in text.splitlines())
    for m in re.finditer(r'\\(?:cite|citep|citet|citeauthor|citeyear|nocite)(?:\[[^\]]*\])?\{([^}]*)\}',text):
        out.extend(x.strip() for x in m.group(1).split(',') if x.strip() and x.strip()!='*')
    return out

checks={}; details={}
checks['root_contract']=sorted(p.name for p in ROOT.iterdir())==['CURRENT-STATE.md','artifact','paper','research-plan.md']
bib=(PAPER/'references.bib').read_text(encoding='utf-8',errors='replace')
tex='\n'.join(p.read_text(encoding='utf-8',errors='replace') for p in [PAPER/'main.tex',PAPER/'supplement.tex'] if p.exists())
bkeys=set(parse_bib_keys(bib)); ckeys=set(citations(tex))
checks['citation_closure']=bkeys==ckeys
details['bib_entries']=len(bkeys); details['cited_keys']=len(ckeys); details['uncited']=sorted(bkeys-ckeys); details['undefined']=sorted(ckeys-bkeys)
ra=HERE/'reference-audit-final.csv'; rows=list(csv.DictReader(ra.open(encoding='utf-8-sig')))
bad=[r for r in rows if r.get('status') in {'unresolved','metadata_mismatch','url_error','invalid_isbn'}]
checks['reference_audit_rows']=len(rows)==len(bkeys) and not bad
details['reference_status_counts']={s:sum(r.get('status')==s for r in rows) for s in sorted({r.get('status') for r in rows})}
rc,out=run([sys.executable,'-m','compileall','-q','.'],cwd=ART,timeout=600); checks['compileall']=rc==0
rc,out=run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=ART,timeout=3600); checks['unit_tests']=rc==0; details['unit_test_tail']=out[-2000:]
if (ART/'verify_revision.py').exists():
    rc,out=run([sys.executable,'verify_revision.py','--root','.'],cwd=ART,timeout=3600); checks['verify_revision']=rc==0; details['verify_revision_tail']=out[-2000:]
rc,out=run([sys.executable,'build.py'],cwd=PAPER,timeout=1800); checks['paper_build']=rc==0; details['paper_build_tail']=out[-3000:]
# Find PDFs generated in paper directory
pdfs=[p for p in PAPER.glob('*.pdf') if p.name.lower()!='template.pdf']
main=[p for p in pdfs if 'supp' not in p.name.lower()]; supp=[p for p in pdfs if 'supp' in p.name.lower()]
checks['pdfs_present']=bool(main and supp)
if main:
    mp=max(main,key=lambda p:p.stat().st_size)
    rc,info=run(['pdfinfo',str(mp)],timeout=120) if shutil.which('pdfinfo') else (0,'')
    m=re.search(r'^Pages:\s*(\d+)',info,re.M); pages=int(m.group(1)) if m else None
    refpage=None
    if shutil.which('pdftotext') and pages:
        for n in range(1,pages+1):
            rc,t=run(['pdftotext','-f',str(n),'-l',str(n),'-layout',str(mp),'-'],timeout=120)
            if re.search(r'^\s*References\s*$',t,re.M):refpage=n;break
    checks['body_page_limit']=refpage is None or refpage-1<=12
    details['main_pdf']={'name':mp.name,'pages':pages,'references_start':refpage,'sha256':hashlib.sha256(mp.read_bytes()).hexdigest()}
    if shutil.which('pdffonts'):
        rc,f=run(['pdffonts',str(mp)],timeout=120)
        un=[]
        for line in f.splitlines()[2:]:
            cols=line.split()
            if len(cols)>=6 and cols[-5].lower()!='yes':un.append(line)
        checks['fonts_embedded']=not un;details['unembedded_fonts']=un
rob=json.loads((HERE/'robustness-summary.json').read_text())
checks['robustness_evidence']=rob.get('normalized_observations',0)>0 and len(rob.get('policies',[]))>=2
details['robustness_observations']=rob.get('normalized_observations'); details['policies']=rob.get('policies')
# Frozen final audit should have no blocking gates
final=json.loads((HERE/'final-blind-review.json').read_text())
checks['frozen_gate_zero_blockers']=not final.get('blocking_gates')
result={'checks':checks,'details':details,'passed':all(checks.values())}
print(json.dumps(result,indent=2,ensure_ascii=False))
if not result['passed']:sys.exit(2)
