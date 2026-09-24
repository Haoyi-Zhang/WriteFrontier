"""Benign crash-prefix reference model. No filesystem or device durability claim.
Each run has an abstract atomic persistent pointer. Payload is immutable; source
storage is reclaimed only after the pointer commit. Metadata capacity and writes
are separate parameters, not silently treated as zero physical bytes.
"""
from copy import deepcopy
from model import Episode,replay

class RecoveryViolation(ValueError):pass

def crash_checks(e:Episode,order,mutation=None,keep_events=False):
    if not replay(e,order)['complete']:raise ValueError('complete legal order required')
    # Units carry distinct retained identities and deterministic logical values.
    old={i:tuple((i,k,17*i+k) for k in range(r.live)) for i,r in enumerate(e.runs)}
    persisted={('old',i):v for i,v in old.items()}
    pointers={i:('old',i) for i in old}
    expected=tuple(sorted(x for values in old.values() for x in values))
    traces=[];checks=0;detected=[]
    def checkpoint(event):
        nonlocal checks
        checks+=1
        recovered=[]
        try:
            for i in range(len(e.runs)):recovered.extend(persisted[pointers[i]])
            valid=tuple(sorted(recovered))==expected
        except KeyError:valid=False
        if not valid:detected.append(event)
        if keep_events:traces.append({'event':event,'retention_ok':valid,
             'pointers':[[i,list(pointers[i])] for i in sorted(pointers)],
             'durable_extents':[[list(k),[list(x) for x in v]] for k,v in sorted(persisted.items())]})
    checkpoint('initial')
    for i in order:
        buf=[]
        for unit in old[i]:
            buf.append(unit)
            checkpoint(f'run {i}: volatile output unit {len(buf)}')
        if mutation=='early-reclaim':
            persisted.pop(('old',i),None);checkpoint(f'run {i}: premature source reclaim')
        if mutation=='publish-before-flush':
            pointers[i]=('new',i);checkpoint(f'run {i}: premature publication')
        persisted[('new',i)]=tuple(buf[:-1] if mutation=='truncated-output' else buf)
        checkpoint(f'run {i}: output flush')
        if mutation=='wrong-owner' and len(e.runs)>1:
            pointers[i]=pointers[(i+1)%len(e.runs)]
        else:pointers[i]=('new',i)
        checkpoint(f'run {i}: atomic publication')
        persisted.pop(('old',i),None);checkpoint(f'run {i}: source reclaim')
    return {'checks':checks,'violations':len(detected),'first_violation':detected[0] if detected else None,
            'events':traces if keep_events else None,
            'payload_units':sum(r.live for r in e.runs),'metadata_commits':len(order)}
