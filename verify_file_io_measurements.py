"""Reconcile saved file-API observations without rerunning or retiming them."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from run_file_io_calibration import summary
from src.epoch_model import deserialize_instance, deserialize_schedule, replay

HERE = Path(__file__).resolve().parent
METHODS = ('two-start', 'coalesced-portfolio', 'optimal')


def require(value, message):
    if not value:
        raise ValueError(message)


def reconcile(rows, plans, recorded):
    require(len(plans) == 20 and len(rows) == 300, 'incomplete trial matrix')
    cases = {p['case_id']: p for p in plans}
    require(len(cases) == 20, 'duplicate case')
    expected = {(c, m, r) for c in cases for m in METHODS for r in range(5)}
    observed = set()
    for row in rows:
        key = row['case_id'], row['method'], row['repeat']
        require(type(row['repeat']) is int and key in expected and key not in observed,
                'invalid or duplicate trial')
        observed.add(key)
        require(type(row['unit_bytes']) is int and row['unit_bytes'] == 512,
                'changed allocation unit')
        case = cases[key[0]]
        instance = deserialize_instance(case['instance'])
        require(instance.quantum == 1 and instance.commit_bytes == 1, 'wrong model slice')
        schedule = deserialize_schedule(case['schedules'][key[1]])
        model = replay(instance, schedule)
        ex, recovery = row['execute'], row['recovery']
        require(type(recovery['complete']) is bool and recovery['complete'], 'failed reopen')
        require(ex['epochs'] == len(schedule) == recovery['committed_epochs'], 'epoch mismatch')
        live = sum(s.live for tier in instance.tiers for s in tier)
        require(ex['model_units'] == model['cost'] == live + len(schedule), 'cost mismatch')
        require(ex['write_bytes'] == ex['payload_write_bytes'] + ex['metadata_write_bytes']
                == 512 * model['cost'], 'file byte mismatch')
        require(ex['payload_write_bytes'] == recovery['verified_payload_bytes'] == 512 * live,
                'retained payload mismatch')
        require(ex['metadata_write_bytes'] == 512 * len(schedule), 'descriptor mismatch')
        require(ex['final_free'] == recovery['final_free'], 'recovered allocation mismatch')
        require(len(ex['events']) == len(schedule), 'missing event')
        for event in ex['events']:
            for field in ('commit_sync_ns', 'payload_sync_ns', 'wall_ns', 'payload_bytes',
                          'descriptor_bytes', 'read_ns', 'write_ns'):
                require(type(event[field]) is int and event[field] >= 0, 'invalid event metric')
        for value in (row['planning_ns'], row['setup']['wall_ns'], ex['wall_ns'],
                      recovery['wall_ns']):
            require(type(value) is int and value >= 0, 'invalid timing')
    require(observed == expected, 'missing trial')
    rebuilt = summary(rows, plans)
    for field, value in rebuilt.items():
        require(recorded.get(field) == value, 'summary mismatch: ' + field)
    for field in ('wall_s', 'process_cpu_s'):
        value = recorded[field]
        require(type(value) in (float, int) and math.isfinite(value) and value >= 0,
                'invalid campaign metric')
    return rebuilt


def verify_saved(root=HERE / 'results/file-io-calibration'):
    rows = [json.loads(line) for line in (root / 'raw-trials.jsonl').read_text('utf-8').splitlines()]
    plans = json.loads((root / 'inputs-and-schedules.json').read_text('utf-8'))
    recorded = json.loads((root / 'summary.json').read_text('utf-8'))
    result = reconcile(rows, plans, recorded)
    bindings = json.loads((root / 'environment.json').read_text('utf-8'))['source_inputs']
    require(len(bindings) == 7, 'incomplete executed source/input binding')
    for relative, binding in bindings.items():
        path = (HERE / relative).resolve(strict=True)
        require(path.is_relative_to(HERE), 'external binding')
        data = path.read_bytes()
        if binding['normalization'] == 'UTF-8/LF':
            data = data.decode('utf-8').replace('\r\n', '\n').encode('utf-8')
        else:
            require(binding['normalization'] == 'binary', 'unknown normalization')
        require(hashlib.sha256(data).hexdigest() == binding['digest'], 'executed source/input changed')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=HERE / 'results/file-io-calibration')
    args = parser.parse_args()
    result = verify_saved(args.results)
    print(json.dumps({k: result[k] for k in ('cases', 'trials', 'file_cost_disagreements',
                                          'all_reopened_reads_verified')}))
