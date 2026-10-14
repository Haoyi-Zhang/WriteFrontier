"""Bounded file replay; no third-party calls, installs, or existing-result writes.

Inputs are read-only. Output directory must be new. Timed invocation is externally
guarded by the shared four-slot measurement runner. Files are under a fresh temp
directory within the output; only these owned temp files are removed on success.
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'src'))
from epoch_model import EpochInstance, Segment, deserialize_instance, replay, serialize_instance, serialize_schedule
from epoch_dp import solve_normal_form, solve_unrestricted
from epoch_policies import two_start_maximum_prefix, coalesced_portfolio
from independent_audit import solve_raw
from file_io_replay import initialize, execute, recover_and_verify


def resources():
    """Windows process memory/I/O and system CPU counters; no waiting interval."""
    result = {'process_cpu_s': time.process_time()}
    if os.name != 'nt':
        result['windows_counters'] = 'unavailable'
        return result
    class Memory(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
             'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
             'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
    class Counts(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ('ReadOperationCount',
                    'WriteOperationCount', 'OtherOperationCount', 'ReadTransferCount',
                    'WriteTransferCount', 'OtherTransferCount')]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    handle = kernel.GetCurrentProcess()
    memory, counts = Memory(), Counts()
    memory.cb = ctypes.sizeof(memory)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
    kernel.GetProcessIoCounters.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counts)]
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.GetProcessIoCounters(handle, ctypes.byref(counts)):
        raise ctypes.WinError(ctypes.get_last_error())
    result['memory'] = {name: getattr(memory, name) for name, _ in memory._fields_[1:]}
    result['process_io'] = {name: getattr(counts, name) for name, _ in counts._fields_}
    times = [wintypes.FILETIME() for _ in range(3)]
    if not kernel.GetSystemTimes(*(ctypes.byref(value) for value in times)):
        raise ctypes.WinError(ctypes.get_last_error())
    result['system_cpu_100ns'] = dict(zip(('idle', 'kernel_including_idle', 'user'),
        [value.dwLowDateTime + (value.dwHighDateTime << 32) for value in times]))
    return result


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')


def source_receipt(input_path):
    files = [HERE / 'run_file_io_calibration.py', HERE / 'tests/test_file_io_replay.py']
    files += [HERE / 'src' / name for name in ('file_io_replay.py', 'epoch_model.py',
              'epoch_dp.py', 'epoch_policies.py', 'independent_audit.py')]
    files.append(input_path)
    return [{'path': str(path.resolve()), 'bytes': path.stat().st_size,
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in files]


def selected_inputs(path, count):
    with gzip.open(path, 'rt', encoding='utf-8') as handle:
        records = json.load(handle)
    # This is a declared slice, not selection by measured speed or optimality.
    selected = [row for row in records if row['domain'] == 'length-3-12' and
                row['instance']['quantum'] == 1 and row['instance']['commit_bytes'] == 1][:count]
    if len(selected) != count:
        raise ValueError('not enough retained q=1,mu=1 inputs')
    cases = [(row['case_id'], deserialize_instance(row['instance']), 'first-retained-patterns')
             for row in selected]
    for reserve in (1, 4, 16):
        tier = tuple(Segment(1, 1, i) for i in range(16))
        cases.append((f'unit-16-r{reserve}', EpochInstance((tier, tier), (reserve, reserve),
                                                       1, 1), 'reserve-control'))
    cases.append(('all-dead', EpochInstance(((Segment(3, 0), Segment(2, 0)),
                                            (Segment(4, 0),)), (0, 0), 1, 1), 'dead-control'))
    return cases


def summary(rows, plans):
    groups = []
    for case in plans:
        record = {'case_id': case['case_id'], 'selection': case['selection'], 'policies': {}}
        for method in ('two-start', 'coalesced-portfolio', 'optimal'):
            values = [row for row in rows if row['case_id'] == case['case_id'] and row['method'] == method]
            record['policies'][method] = {
                'epochs': values[0]['execute']['epochs'],
                'file_write_bytes': values[0]['execute']['write_bytes'],
                'model_cost_units': values[0]['execute']['model_units'],
                'execute_ms_median': statistics.median(v['execute']['wall_ns'] / 1e6 for v in values),
                'execute_ms_min': min(v['execute']['wall_ns'] / 1e6 for v in values),
                'execute_ms_max': max(v['execute']['wall_ns'] / 1e6 for v in values),
                'plan_execute_ms_median': statistics.median((v['planning_ns'] + v['execute']['wall_ns']) / 1e6 for v in values),
                'setup_ms_median': statistics.median(v['setup']['wall_ns'] / 1e6 for v in values),
                'recovery_ms_median': statistics.median(v['recovery']['wall_ns'] / 1e6 for v in values),
            }
        record['greedy_to_opt_file_bytes'] = (record['policies']['two-start']['file_write_bytes'] /
                                           record['policies']['optimal']['file_write_bytes'])
        groups.append(record)
    events = [e for row in rows for e in row['execute']['events']]
    return {'trials': len(rows), 'cases': len(plans), 'all_reopened_reads_verified': all(
        row['recovery']['complete'] for row in rows), 'file_cost_disagreements': sum(
        row['execute']['write_bytes'] != row['execute']['model_units'] * row['unit_bytes'] for row in rows),
        'per_case': groups, 'calibration': {
            'commit_sync_ms_median': statistics.median(e['commit_sync_ns'] / 1e6 for e in events),
            'payload_sync_ms_median_nonempty': statistics.median(e['payload_sync_ns'] / 1e6 for e in events if e['payload_bytes']),
            'scope': 'successful unbuffered file writes and returned fsync, not device bytes; no cold-cache control'}}


def campaign(args):
    input_path, output = Path(args.inputs).resolve(), Path(args.out).resolve()
    output.mkdir(parents=True, exist_ok=False)
    cases = selected_inputs(input_path, args.count)
    receipts = source_receipt(input_path)
    write_new(output / 'source-environment-parameters.json', {
        'utc': datetime.now(timezone.utc).isoformat(), 'python': sys.version,
        'executable': sys.executable, 'platform': platform.platform(), 'cpu_logical': os.cpu_count(),
        'argv': sys.argv, 'unit_bytes': args.unit_bytes, 'count': args.count, 'repeats': args.repeats,
        'method_order': 'rotate three methods by repetition; each case always includes all three',
        'q': 1, 'mu': 1, 'source_receipts': receipts, 'resources_before': resources(),
        'lock_scope': 'caller must acquire all four shared measurement slots; other OS activity not excluded',
        'filesystem_cache': 'normal buffered OS files, unbuffered Python handles; no OS cache purge',
        'time_budget_s': args.seconds, 'output': str(output)})
    plans = []
    for case_id, instance, selection in cases:
        greedy = two_start_maximum_prefix(instance)
        portfolio = coalesced_portfolio(instance)  # evaluated before any optimizer calls
        optimum = solve_normal_form(instance)
        other = solve_unrestricted(instance)
        raw = tuple(tuple((seg.occupied, seg.live) for seg in tier) for tier in instance.tiers)
        oracle = solve_raw(*raw, instance.free, 1, 1)
        if not optimum.feasible or optimum.cost != other.cost or optimum.cost != oracle.cost:
            raise AssertionError('calibration input solvers disagree')
        plans.append({'case_id': case_id, 'selection': selection, 'instance': serialize_instance(instance),
                      'solver_cost_units': optimum.cost, 'raw_oracle': oracle.as_dict(),
                      'schedules': {name: serialize_schedule(value.schedule) for name, value in (
                          ('two-start', greedy), ('coalesced-portfolio', portfolio), ('optimal', optimum))}})
    write_new(output / 'inputs-and-schedules.json', plans)
    methods = {'two-start': two_start_maximum_prefix, 'coalesced-portfolio': coalesced_portfolio,
               'optimal': solve_normal_form}
    rows = []
    start, cpu_start = time.perf_counter(), time.process_time()
    with (output / 'raw-trials.jsonl').open('x', encoding='utf-8') as raw_handle:
        for repeat in range(args.repeats):
            order = list(methods)
            shift = repeat % len(order)
            order = order[shift:] + order[:shift]
            for case_id, instance, selection in cases:
                for ordinal, method in enumerate(order):
                    if time.perf_counter() - start > args.seconds:
                        raise TimeoutError('bounded campaign budget exhausted; raw completed trials preserved')
                    before = resources()
                    plan_start = time.perf_counter_ns()
                    solution = methods[method](instance)
                    planning_ns = time.perf_counter_ns() - plan_start
                    expected = replay(instance, solution.schedule)
                    with tempfile.TemporaryDirectory(prefix='P110-owned-', dir=output) as temp:
                        directory = Path(temp) / 'arenas'
                        setup = initialize(directory, instance, args.unit_bytes)
                        measured = execute(directory, instance, solution.schedule, args.unit_bytes)
                        recovered = recover_and_verify(directory, True)
                    after = resources()
                    if measured['write_bytes'] != expected['cost'] * args.unit_bytes:
                        raise AssertionError('file-byte/model mismatch')
                    row = {'case_id': case_id, 'selection': selection, 'repeat': repeat,
                           'method': method, 'order_in_case': ordinal, 'unit_bytes': args.unit_bytes,
                           'planning_ns': planning_ns, 'setup': setup, 'execute': measured,
                           'recovery': recovered, 'resource_before': before, 'resource_after': after}
                    raw_handle.write(json.dumps(row, sort_keys=True) + '\n')
                    raw_handle.flush()
                    rows.append(row)
            print(json.dumps({'repeat_complete': repeat, 'trials': len(rows),
                              'elapsed_s': time.perf_counter() - start}), flush=True)
    result = summary(rows, plans)
    result['wall_s'] = time.perf_counter() - start
    result['process_cpu_s'] = time.process_time() - cpu_start
    result['resources_after'] = resources()
    write_new(output / 'summary.json', result)
    print(json.dumps({key: result[key] for key in ('cases', 'trials', 'wall_s',
                     'process_cpu_s', 'file_cost_disagreements', 'all_reopened_reads_verified')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', default=str(HERE / 'results/policy-frontier/instances.json.gz'))
    parser.add_argument('--out', required=True)
    parser.add_argument('--count', type=int, default=16)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--unit-bytes', type=int, default=512)
    parser.add_argument('--seconds', type=int, default=180)
    args = parser.parse_args()
    if not 1 <= args.count <= 32 or not 1 <= args.repeats <= 7 or not 1 <= args.seconds <= 300:
        parser.error('bounded count/repeats/seconds limits exceeded')
    campaign(args)
