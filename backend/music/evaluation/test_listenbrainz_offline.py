"""Synthetic contract fixtures only; these do not measure real recommendations."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import unittest
from uuid import UUID

from music.evaluation import listenbrainz_import as imp
from music.evaluation import listenbrainz_eval as ev


BASE = 1_700_000_000
PRIVATE = 'example-private-fixture-account-'


def recording(n):
    return str(UUID(int=n))


def row(user, song, t, *, inserted=None, client=None):
    return {'user_name': PRIVATE + str(user), 'listened_at': BASE + t,
            'inserted_at': None if inserted is None else BASE + inserted,
            'track_metadata': {'mbid_mapping': {'recording_mbid': recording(song)},
                               'additional_info': {} if client is None else {'recording_mbid': recording(client)}}}


def fixture():
    train = [row(u, 1 if u <= 5 else 2, i, inserted=i) for u in range(1, 11) for i in (1, 2)]
    holdout = [row(u, 2 if u <= 5 else 1, i) for u in range(1, 11) for i in (10, 20, 21)]
    return train + holdout + [row(1, 1, 1, inserted=3), row(1, 2, 3, inserted=10),
                              row(1, 3, 20), row(11, 1, 20), row(11, 2, 10)]


def dump_fixture():
    return [{'user_id': int(r['user_name'].removeprefix(PRIVATE)), 'user_name': r['user_name'],
             'recording_msid': r['track_metadata']['mbid_mapping']['recording_mbid'],
             'timestamp': r['listened_at'], 'track_metadata': {}} for r in fixture()]


class ListenBrainzOfflineTest(unittest.TestCase):
    def test_parse_rejects_client_only_and_conflict(self):
        r = row(1, 1, 1, client=2)
        self.assertEqual(imp.parse(r, snapshot=BASE + 50)[0], 'conflicting_recording_mbid')
        del r['track_metadata']['mbid_mapping']
        self.assertEqual(imp.parse(r, snapshot=BASE + 50)[0], 'client_only_unverified')
        self.assertEqual(imp.parse(r, snapshot=BASE)[0], 'invalid_listen_time')
        self.assertFalse(imp.member_allowed('../secret.jsonl', imp.MEMBER))
        with self.assertRaises(imp.ImportErrorSafe):
            next(imp.records(io.BytesIO(b'0' * (imp.MAX_LINE + 1))))

    def test_scratch_budget_is_explicit_and_bounded(self):
        with sqlite3.connect(':memory:') as db:
            with self.assertRaises(imp.ImportErrorSafe):
                imp.init_db(db, 5)
            imp.init_db(db, 3)
            self.assertEqual(db.execute('PRAGMA max_page_count').fetchone()[0] *
                             db.execute('PRAGMA page_size').fetchone()[0], 3 * 1024**3)

    def test_temporal_split_dedup_privacy_and_evaluation(self):
        with sqlite3.connect(':memory:') as db:
            imp.init_db(db)
            counts, lane, _, _ = imp.ingest(db, ((r, 1) for r in fixture()), snapshot=BASE + 50, secret=b'a' * 32)
            data, split = imp.select_dataset(db, train_cut=BASE + 10, validation_cut=BASE + 20)
        self.assertEqual(lane, 'user_name')
        self.assertEqual(counts['duplicates'], 1)
        self.assertEqual(split['train_late_submissions_excluded'], 1)
        self.assertEqual(split['zero_observable_history_sample'], 1)
        self.assertEqual(split['excluded_targets']['test']['out_of_catalog_new_pairs'], 1)
        self.assertEqual({r['recording_mbid'] for r in data['songs']}, {recording(1), recording(2)})
        self.assertNotIn(PRIVATE, json.dumps(data))
        self.assertEqual(split['train_pairs'], 10)
        self.assertTrue(all(r['kind'] == 'LISTEN' and r['positive'] for p in data['partitions'].values() for r in p))
        manifest = {'data_sha256': 'fixture', 'archive_sha256': 'fixture', 'split': split}
        report = ev.evaluate(manifest, data)
        self.assertEqual(report['dataset']['test_target_users'], 11)
        self.assertEqual(report['dataset']['test_target_pairs'], 11)
        self.assertEqual(set(report['methods']), {'HOT', 'NCF', 'USER_CF', 'ITEM_CF'})
        self.assertEqual(report['methods']['HOT']['overall']['ndcg'], 1)
        self.assertIsNone(report['methods']['HOT']['overall']['diversity_jaccard'])
        self.assertTrue(report['methods']['NCF']['groups']['cold_start_0']['suppressed'])
        frozen = {'schema': 'recording-tags-v1', 'available_at': imp.timestamp(BASE), 'source': 'synthetic fixture',
                  'source_url': 'synthetic fixture', 'license': 'fixture', 'tags': {recording(1): ['x'], recording(2): ['x', 'y']}}
        report = ev.evaluate(manifest, data, frozen=frozen)
        self.assertIn('ADAPTIVE_4_RERANK', report['methods'])
        frozen['available_at'] = split['train_cut']
        with self.assertRaises(ValueError):
            ev.evaluate(manifest, data, frozen=frozen)

    def test_historical_archive_schema_and_msid_lane(self):
        rows = dump_fixture()
        with sqlite3.connect(':memory:') as db:
            imp.init_db(db)
            counts, lane, _, _ = imp.ingest(db, ((r, 1) for r in rows), snapshot=BASE + 50,
                                              secret=b'a' * 32, identity='msid')
            data, split = imp.select_dataset(db, train_cut=BASE + 10, validation_cut=BASE + 20, identity='msid')
        self.assertEqual((lane, counts['eligible_with_inserted_at']), ('user_id', 0))
        self.assertTrue(all('recording_mbid' not in item and 'recording_msid' in item for item in data['songs']))
        manifest = {'data_sha256': 'fixture', 'archive_sha256': 'fixture', 'split': split, 'recording_id_kind': 'msid'}
        self.assertEqual(ev.evaluate(manifest, data)['recording_id_kind'], 'msid')
        with self.assertRaisesRegex(ValueError, 'MSID-only'):
            ev.evaluate(manifest, data, frozen={})
        self.assertFalse(imp.member_allowed('metadata/recordings_cache.jsonl', imp.MEMBER))

    @unittest.skipUnless(shutil.which('tar.exe') or shutil.which('tar'), 'tar executable unavailable')
    def test_archive_manifest_integrity_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix='temp_lb_test_') as tmp:
            root = Path(tmp)
            archive = root / 'fixture.tar'
            body = b'\n'.join(json.dumps(r).encode() for r in fixture()) + b'\n'
            with tarfile.open(archive, 'w') as stream:
                for name, payload in [('dump/listens/0.listens', body), ('dump/COPYING', b'CC0 1.0 Universal')]:
                    header = tarfile.TarInfo(name)
                    header.size = len(payload)
                    stream.addfile(header, io.BytesIO(payload))
            checksum = root / 'fixture.sha256'
            checksum.write_text(hashlib.sha256(archive.read_bytes()).hexdigest(), encoding='ascii')
            kwargs = {'source_url': 'synthetic fixture', 'downloaded_at': imp.timestamp(BASE + 50),
                      'snapshot_at': imp.timestamp(BASE + 50), 'secret_path': root / 'test.key'}
            output = root / 'fixture'
            manifest = imp.run(archive, checksum, output, **kwargs)
            self.assertTrue(manifest['archive_cc0_marker_confirmed'])
            self.assertEqual(ev.load(output / 'manifest.json')[0], manifest)
            with self.assertRaises(imp.ImportErrorSafe):
                imp.run(archive, checksum, output, **kwargs)
            with (output / 'data.json').open('a', encoding='utf-8') as dest:
                dest.write(' ')
            with self.assertRaises(ValueError):
                ev.load(output / 'manifest.json')
            with self.assertRaisesRegex(imp.ImportErrorSafe, 'integrity check failed'):
                imp.run(archive, checksum, root / 'rejected', fixed_catalog_manifest=output / 'manifest.json', **kwargs)
            checksum.write_text('0' * 64, encoding='ascii')
            with self.assertRaises(imp.ImportErrorSafe):
                imp.run(archive, checksum, root / 'rejected', **kwargs)


    @unittest.skipUnless(shutil.which('tar.exe') or shutil.which('tar'), 'tar executable unavailable')
    def test_dump_schema_end_to_end(self):
        with tempfile.TemporaryDirectory(prefix='temp_lb_test_') as tmp:
            root = Path(tmp)
            archive = root / 'fixture.tar'
            rows = dump_fixture()
            # Preserve two distinct holdout windows under automatic quantile cuts.
            rows.extend({**r, 'timestamp': BASE + t} for r in dump_fixture()
                        if r['timestamp'] == BASE + 2 for t in range(3, 9))
            with tarfile.open(archive, 'w') as stream:
                pivot = len(rows) // 2
                for name, payload in [('dump/listens/0.listens', b'\n'.join(json.dumps(r).encode() for r in rows[:pivot])),
                                      ('dump/listens/1.listens', b''.join(json.dumps(r).encode() + b'\n' for r in rows[pivot:])),
                                      ('dump/COPYING', b'CC0 1.0 Universal'),
                                      ('dump/SCHEMA_SEQUENCE', b'1'),
                                      ('dump/START_TIMESTAMP', imp.timestamp(BASE).encode()),
                                      ('dump/END_TIMESTAMP', imp.timestamp(BASE + 50).encode())]:
                    header = tarfile.TarInfo(name)
                    header.size = len(payload)
                    stream.addfile(header, io.BytesIO(payload))
            compressed = root / 'fixture.tar.zst'
            tar = shutil.which('tar.exe') or shutil.which('tar')
            subprocess.run([tar, '--zstd', '-cf', str(compressed), '@' + str(archive)], check=True, capture_output=True)
            archive = compressed
            checksum = root / 'fixture.sha256'
            checksum.write_text(imp.digest(archive), encoding='ascii')
            inputs = root / 'inputs'
            manifest = imp.run(archive, checksum, inputs, identity='msid', source_url='synthetic fixture',
                               downloaded_at=imp.timestamp(BASE + 50), snapshot_at=imp.timestamp(BASE + 50),
                               secret_path=root / 'test.key')
            self.assertEqual(manifest['input']['input_lines'], len(rows))
            self.assertEqual(manifest['jsonl_members'], 2)
            self.assertEqual(manifest['archive_metadata'], {'SCHEMA_SEQUENCE': 1,
                             'START_TIMESTAMP': imp.timestamp(BASE), 'END_TIMESTAMP': imp.timestamp(BASE + 50)})
            reports = root / 'reports'
            report = ev.run(inputs / 'manifest.json', reports)
            self.assertEqual(report['archive_sha256'], manifest['archive_sha256'])
            self.assertEqual(report['recording_id_kind'], 'msid')
            self.assertEqual(set(report['methods']), {'HOT', 'USER_CF', 'ITEM_CF', 'NCF'})
            self.assertNotIn(PRIVATE, (inputs / 'data.json').read_text(encoding='utf-8'))
            self.assertEqual(sorted(p.name for p in reports.iterdir()), ['report.json'])
            kwargs = dict(identity='msid', source_url='synthetic fixture', downloaded_at=imp.timestamp(BASE + 50),
                          snapshot_at=imp.timestamp(BASE + 50), secret_path=root / 'test.key',
                          fixed_catalog_manifest=inputs / 'manifest.json')
            expanded = imp.run(archive, checksum, root / 'expanded', max_events=1000, **kwargs)
            self.assertEqual(expanded['fixed_catalog_baseline_data_sha256'], manifest['data_sha256'])
            self.assertEqual(expanded['split'], manifest['split'])
            self.assertEqual(expanded['data_sha256'], manifest['data_sha256'])
            self.assertEqual(expanded['max_events'], 1000)
            with self.assertRaisesRegex(imp.ImportErrorSafe, 'Export event budget exceeded'):
                imp.run(archive, checksum, root / 'too_small', max_events=1, **kwargs)
            self.assertFalse((root / 'too_small').exists())
            with self.assertRaisesRegex(imp.ImportErrorSafe, 'out of bounds'):
                imp.run(archive, checksum, root / 'too_large', max_events=imp.HARD_MAX_EVENTS + 1, **kwargs)
            with self.assertRaisesRegex(ValueError, 'Invalid cutoff or data budget'):
                ev.evaluate({**expanded, 'max_events': 1}, ev.load(root / 'expanded' / 'manifest.json')[1])
            with self.assertRaisesRegex(ValueError, 'Output directory already exists'):
                ev.run(inputs / 'manifest.json', reports)


if __name__ == '__main__':
    unittest.main()
