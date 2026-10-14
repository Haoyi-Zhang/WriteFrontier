"""Exact-unit file replay for the frozen q=1, mu=1 recovery-epoch slice.

Preallocated files implement logical arenas, not disk partitions or SSD tiers.
The single-writer journal publishes a batch through one fixed-size descriptor.
Recovery reconstructs disjoint first-fit output units from the frozen manifest.
Successful fsync is the interface contract, not a physical power-loss proof.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import time
import zlib
from pathlib import Path

from epoch_model import Batch, EpochInstance, deserialize_instance, replay, serialize_instance

MAGIC = b'P110IO01'
HEADER = struct.Struct('<8sIIII')  # sequence, source, start, end
MAX_ARENA_BYTES = 64 * 1024 * 1024


def check_contract(instance, unit_bytes):
    if type(unit_bytes) is not int or not 64 <= unit_bytes <= 65536:
        raise ValueError('unit_bytes must be an integer in [64,65536]')
    if instance.quantum != 1 or instance.commit_bytes != 1:
        raise ValueError('file adapter requires q=1 and mu=1; no padded allocation')
    if sum(instance.lengths) > 512:
        raise ValueError('bounded adapter permits at most 512 segments')
    capacity = tuple(instance.occupied_by_source[s] + instance.free[s] for s in (0, 1))
    if sum(capacity) * unit_bytes > MAX_ARENA_BYTES:
        raise ValueError('combined arena capacity exceeds 64 MiB')
    return capacity


def segment_bytes(source, index, size):
    """Fresh deterministic, nonconstant synthetic retained bytes; no external data."""
    return hashlib.shake_256(f'P110-file-replay:{source}:{index}'.encode()).digest(size)


def encode_record(sequence, batch, unit_bytes):
    body = HEADER.pack(MAGIC, sequence, batch.source, batch.start, batch.end)
    body = body.ljust(unit_bytes - 4, b'\0')
    return body + struct.pack('<I', zlib.crc32(body))


def decode_record(data, sequence):
    if len(data) < 64 or zlib.crc32(data[:-4]) != struct.unpack('<I', data[-4:])[0]:
        raise ValueError('invalid journal descriptor checksum/length')
    magic, number, source, start, end = HEADER.unpack(data[:HEADER.size])
    if magic != MAGIC or number != sequence or any(data[HEADER.size:-4]):
        raise ValueError('invalid journal descriptor header/padding')
    return Batch(source, start, end)


def runs(units):
    """Contiguous runs, preserving first-fit allocation order."""
    if not units:
        return
    start = previous = units[0]
    for current in units[1:]:
        if current != previous + 1:
            yield start, previous - start + 1
            start = current
        previous = current
    yield start, previous - start + 1


class Layout:
    """Disjoint-unit packing, identical for executor and descriptor reconstruction."""
    def __init__(self, instance):
        self.instance = instance
        self.indices = [0, 0]
        self.original = {}
        self.locations = {}
        self.free = []
        for source, tier in enumerate(instance.tiers):
            offset = 0
            for index, segment in enumerate(tier):
                self.original[source, index] = (offset, segment.occupied)
                self.locations[source, index] = (source, list(range(offset, offset + segment.live)))
                offset += segment.occupied
            self.free.append(set(range(offset, offset + instance.free[source])))

    def reserve(self, batch):
        source, target = batch.source, 1 - batch.source
        if batch.start != self.indices[source] or batch.end > len(self.instance.tiers[source]):
            raise ValueError('non-prefix or out-of-range epoch')
        needed = sum(s.live for s in self.instance.tiers[source][batch.start:batch.end])
        if needed > len(self.free[target]):
            raise ValueError('insufficient disjoint shadow units')
        units = sorted(self.free[target])[:needed]
        self.free[target].difference_update(units)
        return units

    def commit(self, batch, units):
        source, target = batch.source, 1 - batch.source
        cursor = 0
        for index in range(batch.start, batch.end):
            segment = self.instance.tiers[source][index]
            self.locations[source, index] = (target, units[cursor:cursor + segment.live])
            cursor += segment.live
            base, occupied = self.original[source, index]
            self.free[source].update(range(base, base + occupied))
        self.indices[source] = batch.end
        if cursor != len(units) or tuple(map(len, self.free)) != self.instance.free_at(*self.indices):
            raise AssertionError('file allocator disagrees with model free-space identity')


class IO:
    """Successful file-byte counts, not device traffic or filesystem metadata."""
    def __init__(self):
        self.stats = {key: 0 for key in ('read_bytes', 'write_bytes', 'read_calls',
                                       'write_calls', 'sync_calls', 'sync_ns', 'read_ns', 'write_ns')}

    def write(self, handle, data):
        view = memoryview(data)
        start = time.perf_counter_ns()
        while view:
            count = handle.write(view)
            if count is None or count <= 0:
                raise OSError('file write made no progress')
            self.stats['write_calls'] += 1
            self.stats['write_bytes'] += count
            view = view[count:]
        self.stats['write_ns'] += time.perf_counter_ns() - start

    def read(self, handle, count):
        start = time.perf_counter_ns()
        parts = []
        remaining = count
        while remaining:
            data = handle.read(remaining)
            self.stats['read_calls'] += 1
            self.stats['read_bytes'] += len(data)
            if not data:
                raise OSError('short file read')
            parts.append(data)
            remaining -= len(data)
        self.stats['read_ns'] += time.perf_counter_ns() - start
        return b''.join(parts)

    def sync(self, handle):
        start = time.perf_counter_ns()
        os.fsync(handle.fileno())  # unbuffered handles, no hidden Python buffer
        self.stats['sync_ns'] += time.perf_counter_ns() - start
        self.stats['sync_calls'] += 1


def initialize(directory, instance, unit_bytes=512):
    """Create NEW files only. Provision all file bytes; no sparse truncation."""
    capacity = check_contract(instance, unit_bytes)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    counter = IO()
    start = time.perf_counter_ns()
    for source, tier in enumerate(instance.tiers):
        with (directory / f'arena{source}.bin').open('xb', buffering=0) as handle:
            for index, segment in enumerate(tier):
                counter.write(handle, segment_bytes(source, index, segment.live * unit_bytes))
                counter.write(handle, b'\0' * ((segment.occupied - segment.live) * unit_bytes))
            counter.write(handle, b'\0' * (instance.free[source] * unit_bytes))
            counter.sync(handle)
    with (directory / 'journal.bin').open('xb', buffering=0) as handle:
        counter.write(handle, b'\0' * (sum(instance.lengths) * unit_bytes))
        counter.sync(handle)
    manifest = json.dumps({'instance': serialize_instance(instance), 'unit_bytes': unit_bytes},
                          sort_keys=True, separators=(',', ':')).encode() + b'\n'
    with (directory / 'manifest.json').open('xb', buffering=0) as handle:
        counter.write(handle, manifest)
        counter.sync(handle)
    return {'wall_ns': time.perf_counter_ns() - start, 'arena_bytes': sum(capacity) * unit_bytes,
            'journal_capacity_bytes': sum(instance.lengths) * unit_bytes,
            'manifest_bytes': len(manifest), **counter.stats}


def execute(directory, instance, schedule, unit_bytes=512, after_event=None):
    """Execute a complete valid schedule. Callback supports bounded process-stop tests."""
    check_contract(instance, unit_bytes)
    schedule = tuple(schedule)
    expected = replay(instance, schedule)  # reject malformed/incomplete input before writes
    directory = Path(directory)
    stored = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if stored != {'instance': serialize_instance(instance), 'unit_bytes': unit_bytes}:
        raise ValueError('manifest does not match execution contract')
    if any((directory / f'arena{s}.bin').stat().st_size !=
           (instance.occupied_by_source[s] + instance.free[s]) * unit_bytes for s in (0, 1)):
        raise ValueError('arena size mismatch')
    counter = IO()
    layout = Layout(instance)
    events = []
    start = time.perf_counter_ns()
    with (directory / 'arena0.bin').open('r+b', buffering=0) as a0, \
         (directory / 'arena1.bin').open('r+b', buffering=0) as a1, \
         (directory / 'journal.bin').open('r+b', buffering=0) as journal:
        arenas = (a0, a1)
        if journal.read() != b'\0' * (sum(instance.lengths) * unit_bytes):
            raise ValueError('executor requires a fresh zero journal')
        for epoch, batch in enumerate(schedule):
            epoch_start = time.perf_counter_ns()
            read_start = counter.stats['read_ns']
            write_start = counter.stats['write_ns']
            sync_start = counter.stats['sync_ns']
            before = tuple(map(len, layout.free))
            units = layout.reserve(batch)
            pieces = []
            for index in range(batch.start, batch.end):
                live = instance.tiers[batch.source][index].live
                if live:
                    base, _ = layout.original[batch.source, index]
                    arenas[batch.source].seek(base * unit_bytes)
                    pieces.append(counter.read(arenas[batch.source], live * unit_bytes))
            payload = b''.join(pieces)
            target = 1 - batch.source
            cursor = 0
            for base, count in runs(units):
                arenas[target].seek(base * unit_bytes)
                amount = count * unit_bytes
                counter.write(arenas[target], payload[cursor:cursor + amount])
                cursor += amount
            if cursor != len(payload):
                raise AssertionError('payload allocation length mismatch')
            if after_event:
                after_event(epoch, 'copy')
            if units:
                counter.sync(arenas[target])
            payload_sync_ns = counter.stats['sync_ns'] - sync_start
            if after_event:
                after_event(epoch, 'payload-sync')
            journal.seek(epoch * unit_bytes)
            counter.write(journal, encode_record(epoch, batch, unit_bytes))
            sync_start = counter.stats['sync_ns']
            counter.sync(journal)
            commit_sync_ns = counter.stats['sync_ns'] - sync_start
            if after_event:
                after_event(epoch, 'commit-sync')
            layout.commit(batch, units)  # reclaim only after descriptor sync returns
            if after_event:
                after_event(epoch, 'reclaim')
            events.append({'epoch': epoch, 'source': batch.source, 'start': batch.start,
                           'end': batch.end, 'before': before,
                           'after': tuple(map(len, layout.free)),
                           'payload_bytes': len(payload), 'descriptor_bytes': unit_bytes,
                           'destination_extents': list(runs(units)),
                           'wall_ns': time.perf_counter_ns() - epoch_start,
                           'read_ns': counter.stats['read_ns'] - read_start,
                           'write_ns': counter.stats['write_ns'] - write_start,
                           'payload_sync_ns': payload_sync_ns, 'commit_sync_ns': commit_sync_ns})
    wall_ns = time.perf_counter_ns() - start
    if counter.stats['write_bytes'] != expected['cost'] * unit_bytes:
        raise AssertionError('actual successful file writes disagree with frozen cost')
    return {'wall_ns': wall_ns, 'epochs': len(schedule), 'model_units': expected['cost'],
            'preflight_read_bytes': (directory / 'manifest.json').stat().st_size +
                                    sum(instance.lengths) * unit_bytes,
            'payload_write_bytes': instance.total_live * unit_bytes,
            'metadata_write_bytes': len(schedule) * unit_bytes,
            'final_free': tuple(map(len, layout.free)), 'events': events, **counter.stats}


def recover_and_verify(directory, require_complete=False):
    """Close/reopen, replay journal, and compare every retained byte to known data.

    Accept only a valid descriptor prefix. A last torn descriptor can be ignored
    in process-stop tests; arbitrary device loss/reordering is outside the contract.
    """
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    instance = deserialize_instance(manifest['instance'])
    unit_bytes = manifest['unit_bytes']
    check_contract(instance, unit_bytes)
    layout = Layout(instance)
    schedule = []
    tail = 'zero'
    start = time.perf_counter_ns()
    counter = IO()
    with (directory / 'journal.bin').open('rb', buffering=0) as journal:
        for epoch in range(sum(instance.lengths)):
            record = counter.read(journal, unit_bytes)
            if record == b'\0' * unit_bytes:
                break
            try:
                batch = decode_record(record, epoch)
                units = layout.reserve(batch)
            except ValueError:
                tail = 'invalid'
                break
            layout.commit(batch, units)
            schedule.append(batch)
    checked = replay(instance, schedule, require_complete=require_complete)
    if require_complete and tail == 'invalid':
        raise ValueError('invalid journal in complete replay')
    verified = 0
    with (directory / 'arena0.bin').open('rb', buffering=0) as a0, \
         (directory / 'arena1.bin').open('rb', buffering=0) as a1:
        arenas = (a0, a1)
        for (source, index), (target, units) in layout.locations.items():
            data = []
            for base, count in runs(units):
                arenas[target].seek(base * unit_bytes)
                data.append(counter.read(arenas[target], count * unit_bytes))
            expected = segment_bytes(source, index, instance.tiers[source][index].live * unit_bytes)
            if b''.join(data) != expected:
                raise ValueError(f'corrupt retained payload: source={source}, segment={index}')
            verified += len(expected)
    return {'wall_ns': time.perf_counter_ns() - start, 'complete': checked['complete'],
            'committed_epochs': len(schedule), 'verified_payload_bytes': verified,
            'tail': tail, 'final_free': checked['free'], **counter.stats}
