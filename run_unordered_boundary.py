#!/usr/bin/env python3
"""Bounded standard-library reproduction; one process, no network, no external programs."""
import argparse,csv,itertools,json,os,resource,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from model import Run,Episode,guarded_order,universal_guard,replay
from oracle import exact_order,permutation_oracle,chunk_oracle,any_deadlock,reserve_frontier
from certificates import encode,feasible_certificate,infeasible_certificate
from check_certificate import check,InvalidCertificate
from recovery import crash_checks

def bound():
    if not __debug__:
        raise RuntimeError("validation requires assertions; do not use Python -O")
    if hasattr(os,'sched_getaffinity'):
        os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
    resource.setrlimit(resource.RLIMIT_AS,(3*1024**3,3*1024**3))
    resource.setrlimit(resource.RLIMIT_CPU,(2700,2700))

def writejson(p,data):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')

def cases():
    types=tuple(Run(s,l+garbage,l) for s in (0,1) for l in (1,2,3) for garbage in (0,1))
    k=0
    for n in range(1,5):
        for runs in itertools.combinations_with_replacement(types,n):
            for f0 in range(6):
                for f1 in range(6):
                    yield k,Episode(runs,(f0,f1)); k+=1

FIELDS=['case','runs','f0','f1','final_fits','feasible','guard','any_deadlock',
        'fifo_complete','small_complete','large_complete','garbage_complete',
        'chunk_feasible','subset_states','chunk_states','permutations_tried']

def run_part(out,part,part_size=8192):
    start=part*part_size;stop=start+part_size; rows=0
    p=out/f'oracle-{part:02d}.csv'
    with p.open('w',newline='') as f:
        wr=csv.DictWriter(f,fieldnames=FIELDS);wr.writeheader()
        for k,e in itertools.islice(cases(),start,stop):
            exact=exact_order(e);feasible=exact['order'] is not None
            perm,pcount=permutation_oracle(e)
            chunk,nchunk=chunk_oracle(e)
            assert feasible==(perm is not None)==chunk,(k,'oracle disagreement')
            dead=any_deadlock(e) is not None
            guard=universal_guard(e)
            assert not guard or (feasible and not dead),(k,'guard refuted')
            if feasible:
                assert replay(e,exact['order'])['complete']
                assert check(feasible_certificate(e,exact['order']))['valid']
            else:
                assert check(infeasible_certificate(e))['valid']
            policies=[int(len(guarded_order(e,p))==len(e.runs)) for p in ('fifo','small','large','garbage')]
            wr.writerow(dict(zip(FIELDS,[k,';'.join(f'{r.source}:{r.occupied}:{r.live}' for r in e.runs),*e.free,
                int(e.final_fits()),int(feasible),int(guard),int(dead),*policies,int(chunk),exact['states'],nchunk,pcount])))
            rows+=1
    return {'suite':'exhaustive','part':part,'start_case':start,'rows':rows}

def partition(items,B):
    """Independent exact 3-partition backtracking, not migration-state enumeration."""
    if not items:return True
    if len(items)%3 or sum(items)!=(len(items)//3)*B:return False
    x=items[0]
    for i in range(1,len(items)):
        for j in range(i+1,len(items)):
            if x+items[i]+items[j]==B and partition(tuple(v for k,v in enumerate(items) if k not in (0,i,j)),B):
                return True
    return False

def boundary_and_reduction(out):
    count=0
    with (out/'boundary.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['max_into_0','max_into_1','blocked_f0','blocked_f1','blocked','plus_one_into_0_safe','plus_one_into_1_safe'])
        for a in range(1,65):
            for b in range(1,65):
                runs=(Run(0,b,b),Run(1,a,a));e=Episode(runs,(a-1,b-1))
                assert e.final_fits() and exact_order(e)['order'] is None
                for newfree in [(a,b-1),(a-1,b)]:
                    q=Episode(runs,newfree)
                    assert universal_guard(q) and any_deadlock(q) is None
                w.writerow([a,b,a-1,b-1,1,1,1]);count+=1
    red=[]
    for B in range(12,25):
        vals=range(B//4+1,(B+1)//2)
        for n in (6,9):
            for items in itertools.combinations_with_replacement(vals,n):
                if sum(items)!=(n//3)*B:continue
                e=Episode(tuple(Run(0,x,x) for x in items)+tuple(Run(1,B,B) for _ in range(n//3)),(0,B))
                a=exact_order(e);truth=partition(items,B)
                assert (a['order'] is not None)==truth
                red.append({'B':B,'items':items,'partition':truth,'migration':a['order'] is not None,'subset_states':a['states']})
    writejson(out/'reduction.json',red)
    return {'suite':'boundary-reduction','boundary_cases':count,'reduction_cases':len(red),
            'reduction_positive':sum(x['partition'] for x in red),'reduction_negative':sum(not x['partition'] for x in red)}

def examples_and_recovery(out):
    named={
      'blocked_exchange':Episode((Run(0,2,2),Run(1,2,2)),(1,1)),
      'order_sensitive':Episode(tuple(Run(s,l,l) for s,l in [(0,1),(1,1),(0,2),(1,2)]),(1,1)),
      'garbage_release':Episode((Run(0,4,1),Run(1,4,3),Run(0,3,2)),(1,1)),
      'final_deficit':Episode((Run(0,3,3),Run(0,2,2)),(0,1)),
      'balanced_partition_no':Episode(tuple(Run(0,x,x) for x in [4]*6+[6]*6)+tuple(Run(1,15,15) for _ in range(4)),(0,15))}
    proofs=out/'certificates';proofs.mkdir(exist_ok=True)
    detail={};front=[]
    for name,e in named.items():
        result=exact_order(e)
        cert=feasible_certificate(e,result['order']) if result['order'] is not None else infeasible_certificate(e)
        checked=check(cert);writejson(proofs/(name+'.json'),cert)
        detail[name]={'instance':encode(e),'oracle':result,'certificate':checked,
            'fifo_prefix':guarded_order(e),'guard':universal_guard(e),'deadlock':any_deadlock(e)}
        if len(e.runs)<=4:
            detail[name]['frontier']=reserve_frontier(e.runs,6)
            for x,y in detail[name]['frontier']:front.append([name,x,y])
    with (out/'frontiers.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['case','f0','f1']);w.writerows(front)
    writejson(out/'examples.json',detail)
    e=named['order_sensitive'];order=exact_order(e)['order']
    writejson(out/'crash_example.json',crash_checks(e,order,keep_events=True))
    # Every feasible episode with at most two runs in the exhaustive grid; all crash prefixes.
    checked=0;prefixes=0;mutation_cases=0;mutation_prefixes=0;violations=0
    for k,e in cases():
        if len(e.runs)>2:break
        q=exact_order(e)
        if q['order'] is None:continue
        result=crash_checks(e,q['order'])
        assert result['violations']==0
        checked+=1;prefixes+=result['checks']
        ms=['early-reclaim','publish-before-flush','truncated-output']
        if len(e.runs)>1:ms.append('wrong-owner')
        for m in ms:
            bad=crash_checks(e,q['order'],mutation=m)
            assert bad['violations']>0,(k,m)
            mutation_cases+=1;mutation_prefixes+=bad['checks'];violations+=bad['violations']
    result={'suite':'examples-recovery','feasible_episodes':checked,'valid_crash_prefixes':prefixes,
        'mutation_episode_variants':mutation_cases,'mutation_prefixes':mutation_prefixes,'detected_invalid_prefixes':violations,
        'mutation_detection':'all tested variants had at least one invalid retained-value recovery',
        'crash_model':'loss of unflushed payload; atomic run-pointer publication; completed source erase; no torn metadata or device model'}
    writejson(out/'recovery_summary.json',result)
    return result

def summarize(out):
    totals={k:0 for k in ['cases','final_fits','feasible','guard','any_deadlock','final_fit_infeasible','feasible_order_sensitive','safe_but_guard_rejected','fifo_complete','small_complete','large_complete','garbage_complete','subset_states','chunk_states','permutations_tried']}
    seen=set();max_subset=max_chunk=0
    for p in sorted(out.glob('oracle-*.csv')):
        for r in csv.DictReader(p.open()):
            k=int(r['case']);assert k not in seen,'overlapping parts';seen.add(k)
            totals['cases']+=1
            for name in ['final_fits','feasible','guard','any_deadlock','fifo_complete','small_complete','large_complete','garbage_complete','subset_states','chunk_states','permutations_tried']:totals[name]+=int(r[name])
            fit=bool(int(r['final_fits']));feas=bool(int(r['feasible']));dead=bool(int(r['any_deadlock']));guard=bool(int(r['guard']))
            totals['final_fit_infeasible']+=int(fit and not feas)
            totals['feasible_order_sensitive']+=int(feas and dead)
            totals['safe_but_guard_rejected']+=int(feas and not dead and not guard)
            max_subset=max(max_subset,int(r['subset_states']));max_chunk=max(max_chunk,int(r['chunk_states']))
    complete=len(seen)==65484 and seen==set(range(65484))
    totals.update({'complete_exhaustive_grid':complete,'max_subset_states':max_subset,'max_chunk_states':max_chunk,
        'corpus_definition':'all multisets of 1..4 runs from 12 (source,live,garbage) types; each free coordinate 0..5',
        'interpretation':'finite descriptive counts, not workload frequencies or independent research reproduction'})
    writejson(out/'summary.json',totals)
    return totals

def main():
    p=argparse.ArgumentParser();p.add_argument('--part',type=int);p.add_argument('--all',action='store_true');p.add_argument('--examples',action='store_true');p.add_argument('--boundary',action='store_true');p.add_argument('--summarize',action='store_true');p.add_argument('--out',type=Path,default=ROOT/'results')
    a=p.parse_args()
    if not any([a.part is not None,a.all,a.examples,a.boundary,a.summarize]):p.error('select --all or a suite')
    if a.part is not None and not 0<=a.part<=7:p.error('--part must be 0..7')
    bound();a.out.mkdir(parents=True,exist_ok=True)
    suites=[]
    if a.all:suites.extend((f'exhaustive-{i}',lambda i=i:run_part(a.out,i)) for i in range(8))
    elif a.part is not None:suites.append((f'exhaustive-{a.part}',lambda:run_part(a.out,a.part)))
    if a.all or a.examples:suites.append(('examples-recovery',lambda:examples_and_recovery(a.out)))
    if a.all or a.boundary:suites.append(('boundary-reduction',lambda:boundary_and_reduction(a.out)))
    for name,fn in suites:
        cpu=time.process_time();wall=time.monotonic();data=fn()
        vm=[x.strip() for x in Path('/proc/self/status').read_text().splitlines() if x.startswith('VmSwap:')]
        if vm and int(vm[0].split()[1]):raise RuntimeError('no-swap contract violated')
        measure={'suite':name,'cpu_seconds':time.process_time()-cpu,'wall_seconds':time.monotonic()-wall,
                 'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'swap':vm,'result':data}
        writejson(a.out/'runtime'/(name+'.json'),measure)
        print(json.dumps(measure,sort_keys=True),flush=True)
    if a.all or a.summarize:print(json.dumps(summarize(a.out),sort_keys=True),flush=True)

if __name__=='__main__':main()
