import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from epoch_model import Batch, EpochInstance, Segment, replay
from epoch_dp import solve_normal_form
from file_io_replay import (IO, Layout, check_contract, decode_record, encode_record,
                            execute, initialize, recover_and_verify)


def fixture():
    return EpochInstance(((Segment(3, 1), Segment(2, 2), Segment(1, 0)),
                          (Segment(2, 1), Segment(1, 1), Segment(2, 0))), (1, 1), 1, 1)


class FileReplayTests(unittest.TestCase):
    def test_actual_file_bytes_and_reopen(self):
        instance = fixture()
        schedule = solve_normal_form(instance).schedule
        with tempfile.TemporaryDirectory(prefix='P110-test-') as temp:
            directory = Path(temp) / 'files'
            setup = initialize(directory, instance, 64)
            result = execute(directory, instance, schedule, 64)
            recovery = recover_and_verify(directory, True)
            self.assertEqual(result['write_bytes'], replay(instance, schedule)['cost'] * 64)
            self.assertEqual(result['read_bytes'], instance.total_live * 64)
            self.assertEqual(recovery['verified_payload_bytes'], instance.total_live * 64)
            self.assertEqual(result['final_free'], instance.final_free())
            self.assertEqual(setup['sync_calls'], 4)
            self.assertEqual(setup['write_bytes'], setup['arena_bytes'] +
                             setup['journal_capacity_bytes'] + setup['manifest_bytes'])

    def test_every_phase_process_stop_then_reopen(self):
        instance = fixture()
        epochs = len(solve_normal_form(instance).schedule)
        with tempfile.TemporaryDirectory(prefix='P110-stop-') as temp:
            for epoch in range(epochs):
                for stage in ('copy', 'payload-sync', 'commit-sync', 'reclaim'):
                    directory = Path(temp) / f'{epoch}-{stage}'
                    child = subprocess.run([sys.executable, '-B', __file__, '--stop',
                                            str(directory), str(epoch), stage],
                                           capture_output=True, timeout=20)
                    self.assertEqual(child.returncode, 17, child.stderr.decode(errors='replace'))
                    recovered = recover_and_verify(directory)
                    committed = epoch + (stage in ('commit-sync', 'reclaim'))
                    self.assertEqual(recovered['committed_epochs'], committed)
                    self.assertEqual(recovered['verified_payload_bytes'], instance.total_live * 64)

    def test_zero_live_still_pays_one_descriptor(self):
        instance = EpochInstance(((Segment(1, 0),), (Segment(2, 0),)), (0, 0), 1, 1)
        with tempfile.TemporaryDirectory(prefix='P110-dead-') as temp:
            directory = Path(temp) / 'files'
            initialize(directory, instance, 64)
            result = execute(directory, instance, (Batch(0, 0, 1), Batch(1, 0, 1)), 64)
            self.assertEqual(result['payload_write_bytes'], 0)
            self.assertEqual(result['write_bytes'], 128)
            self.assertEqual(result['sync_calls'], 2)
            self.assertTrue(recover_and_verify(directory, True)['complete'])

    def test_corrupt_payload_is_detected(self):
        instance = EpochInstance(((Segment(1, 1),), ()), (0, 1), 1, 1)
        with tempfile.TemporaryDirectory(prefix='P110-corrupt-') as temp:
            directory = Path(temp) / 'files'
            initialize(directory, instance, 64)
            execute(directory, instance, (Batch(0, 0, 1),), 64)
            with (directory / 'arena1.bin').open('r+b', buffering=0) as handle:
                handle.write(b'X')
                os.fsync(handle.fileno())
            with self.assertRaisesRegex(ValueError, 'corrupt retained'):
                recover_and_verify(directory, True)

    def test_torn_last_descriptor_before_reclaim_keeps_old_copy(self):
        instance = fixture()
        with tempfile.TemporaryDirectory(prefix='P110-tail-') as temp:
            directory = Path(temp) / 'files'
            child = subprocess.run([sys.executable, '-B', __file__, '--stop', str(directory),
                                    '0', 'payload-sync'], capture_output=True, timeout=20)
            self.assertEqual(child.returncode, 17)
            record = encode_record(0, solve_normal_form(instance).schedule[0], 64)
            with (directory / 'journal.bin').open('r+b', buffering=0) as handle:
                handle.write(record[:20])
                os.fsync(handle.fileno())
            result = recover_and_verify(directory)
            self.assertEqual(result['tail'], 'invalid')
            self.assertEqual(result['committed_epochs'], 0)

    def test_reject_changed_guard_cost_or_manifest(self):
        with tempfile.TemporaryDirectory(prefix='P110-reject-') as temp:
            directory = Path(temp) / 'files'
            instance = fixture()
            initialize(directory, instance, 64)
            with self.assertRaises(ValueError):
                execute(directory, instance, (Batch(0, 0, 3), Batch(1, 0, 3)), 64)
            changed = EpochInstance(instance.tiers, (10, 10), 1, 1)
            with self.assertRaisesRegex(ValueError, 'manifest'):
                execute(directory, changed, solve_normal_form(changed).schedule, 64)
            with self.assertRaises(ValueError):
                check_contract(EpochInstance(instance.tiers, instance.free, 4, 1), 64)
            with self.assertRaises(ValueError):
                check_contract(EpochInstance(instance.tiers, instance.free, 1, 0), 64)
            with self.assertRaises(ValueError):
                check_contract(instance, True)

    def test_new_files_only_and_no_second_execution(self):
        instance = fixture()
        with tempfile.TemporaryDirectory(prefix='P110-fresh-') as temp:
            directory = Path(temp) / 'files'
            initialize(directory, instance, 64)
            with self.assertRaises(FileExistsError):
                initialize(directory, instance, 64)
            schedule = solve_normal_form(instance).schedule
            execute(directory, instance, schedule, 64)
            with self.assertRaisesRegex(ValueError, 'fresh zero journal'):
                execute(directory, instance, schedule, 64)

    def test_fragmented_reserve_realizes_aggregate_guard(self):
        instance = fixture()
        layout = Layout(instance)
        for batch in solve_normal_form(instance).schedule:
            units = layout.reserve(batch)
            self.assertEqual(len(set(units)), len(units))
            layout.commit(batch, units)
        self.assertEqual(tuple(map(len, layout.free)), instance.final_free())
        selected = set()
        for target, units in layout.locations.values():
            for unit in units:
                self.assertNotIn((target, unit), selected)
                selected.add((target, unit))

    def test_real_scatter_copy_when_no_contiguous_extent_fits(self):
        instance = EpochInstance(((Segment(3, 1), Segment(1, 1), Segment(1, 1)),
                                  (Segment(4, 4),)), (2, 1), 1, 1)
        schedule = (Batch(0, 0, 1), Batch(1, 0, 1), Batch(0, 1, 3))
        with tempfile.TemporaryDirectory(prefix='P110-scatter-') as temp:
            directory = Path(temp) / 'files'
            initialize(directory, instance, 64)
            measured = execute(directory, instance, schedule, 64)
            self.assertEqual(measured['events'][1]['destination_extents'], [(0, 3), (5, 1)])
            self.assertTrue(recover_and_verify(directory, True)['complete'])

    def test_empty_episode(self):
        instance = EpochInstance(((), ()), (0, 0), 1, 1)
        with tempfile.TemporaryDirectory(prefix='P110-empty-') as temp:
            directory = Path(temp) / 'files'
            initialize(directory, instance, 64)
            measured = execute(directory, instance, (), 64)
            self.assertEqual(measured['write_bytes'], 0)
            self.assertEqual(measured['sync_calls'], 0)
            self.assertTrue(recover_and_verify(directory, True)['complete'])

    def test_record_sequence_crc_and_short_write_accounting(self):
        data = encode_record(2, Batch(1, 0, 2), 64)
        self.assertEqual(decode_record(data, 2), Batch(1, 0, 2))
        for damaged in (data[:15], data[:-1] + bytes([data[-1] ^ 1])):
            with self.assertRaises(ValueError):
                decode_record(damaged, 2)
        with self.assertRaises(ValueError):
            decode_record(data, 1)
        class ShortWriter(io.BytesIO):
            def write(self, buffer):
                return super().write(buffer[:3])
        counter, handle = IO(), ShortWriter()
        counter.write(handle, b'abcdefgh')
        self.assertEqual(handle.getvalue(), b'abcdefgh')
        self.assertEqual(counter.stats['write_bytes'], 8)
        self.assertEqual(counter.stats['write_calls'], 3)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--stop':
        directory, epoch, stage = Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
        instance = fixture()
        initialize(directory, instance, 64)
        def stop(number, event):
            if number == epoch and event == stage:
                os._exit(17)  # this child only; no OS flush on exit
        execute(directory, instance, solve_normal_form(instance).schedule, 64, stop)
        raise RuntimeError('requested stop point not reached')
    unittest.main()
