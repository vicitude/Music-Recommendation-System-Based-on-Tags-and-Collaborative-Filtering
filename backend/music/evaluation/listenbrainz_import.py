"""Convert a local ListenBrainz JSONL archive into a private, bounded research dataset.

No Django, network, production credentials or business database are used.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from uuid import UUID


SCHEMA = 'listenbrainz-offline-v1'
MIN_TS = 1033430400
MAX_LINE = 1024 * 1024
MAX_MEMBERS = 256
MAX_ARCHIVE = 600_000_000
MAX_STREAM = 8 * 1024**3
MAX_EVENTS = 200_000
HARD_MAX_EVENTS = 500_000
MAX_DATA_BYTES = 80_000_000
MIN_TRAIN_LISTENERS = 3
MAX_USERS = 500
MAX_ITEMS = 2000
MEMBER = re.compile(r'(?:[A-Za-z0-9_.-]+/)*[0-9]+\.listens')
IDENTITIES = ('mbid', 'msid')
METADATA = re.compile(r'(?:[A-Za-z0-9_.-]+/)*(?:COPYING|LICENSE|LICENSE\.txt|SCHEMA_SEQUENCE|TIMESTAMP|START_TIMESTAMP|END_TIMESTAMP)')


class ImportErrorSafe(ValueError):
    """Diagnostic which never includes an input record or account identifier."""


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def write_json(path, obj):
    with Path(path).open('x', encoding='utf-8', newline='\n') as dest:
        json.dump(obj, dest, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))
        dest.write('\n')


def timestamp(second):
    return datetime.fromtimestamp(second, tz=timezone.utc).isoformat()


def epoch(text):
    value = datetime.fromisoformat(text.replace('Z', '+00:00'))
    if value.utcoffset() is None or value.microsecond:
        raise ImportErrorSafe('Expected a timezone-aware whole-second timestamp')
    return int(value.timestamp())


def mbid(value):
    if not isinstance(value, str) or len(value) != 36:
        return None
    try:
        parsed = UUID(value)
    except ValueError:
        return None
    return str(parsed) if parsed.int and str(parsed) == value.lower() else None


def account_key(row):
    # Prefer a stable numeric ID when the whole data profile supplies it. Never
    # mix namespaces within one import; the caller locks the first usable lane.
    uid = row.get('user_id')
    if type(uid) is int and 0 < uid <= 2**63 - 1:
        return 'user_id', str(uid)
    name = row.get('user_name')
    if isinstance(name, str) and name.strip() and len(name) <= 256:
        return 'user_name', name
    return None, None


def parse(row, *, snapshot, user_field=None, identity='mbid'):
    if not isinstance(row, dict):
        return 'invalid_json_shape', None
    if 'timestamp' in row and 'listened_at' in row and row['timestamp'] != row['listened_at']:
        return 'conflicting_listen_time', None
    listened = row.get('timestamp', row.get('listened_at'))
    if type(listened) is not int or not MIN_TS <= listened <= snapshot:
        return 'invalid_listen_time', None
    lane, key = account_key(row)
    if key is None or user_field is not None and lane != user_field:
        return 'missing_or_inconsistent_account_key', None
    metadata = row.get('track_metadata')
    if not isinstance(metadata, dict):
        return 'missing_track_metadata', None
    server = metadata.get('mbid_mapping')
    client = metadata.get('additional_info')
    resolved = mbid(server.get('recording_mbid')) if isinstance(server, dict) else None
    submitted = mbid(client.get('recording_mbid')) if isinstance(client, dict) else None
    if identity == 'msid':
        resolved = mbid(row.get('recording_msid'))
        if not resolved:
            return 'missing_recording_msid', None
    elif resolved and submitted and resolved != submitted:
        return 'conflicting_recording_mbid', None
    elif not resolved:
        # A UUID from the client alone does not establish it is a Recording ID.
        return 'client_only_unverified' if submitted else 'missing_resolved_mbid', None
    inserted = row.get('inserted_at')
    if type(inserted) is not int or not MIN_TS <= inserted <= snapshot:
        inserted = None
    return 'eligible', (lane, key, resolved, listened, inserted)


def member_allowed(name, pattern):
    path = PurePosixPath(name)
    return bool(pattern.fullmatch(name) and all(p not in {'.', '..'} and not p.startswith('-') for p in name.split('/')) and not path.is_absolute())


@contextmanager
def tar_output(tar, args):
    with subprocess.Popen([tar, *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        try:
            yield proc.stdout
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        if proc.wait() != 0:
            raise ImportErrorSafe('Archive reader returned a nonzero exit')


def members(tar, archive):
    data, policy, parquet = [], [], 0
    with tar_output(tar, ['-tf', str(archive)]) as stream:
        for count, raw in enumerate(stream, 1):
            if count > MAX_MEMBERS:
                raise ImportErrorSafe('Archive member limit exceeded')
            name = raw.rstrip(b'\r\n').decode('utf-8', errors='replace')
            if member_allowed(name, MEMBER):
                data.append(name)
            if member_allowed(name, METADATA):
                policy.append(name)
            parquet += name.endswith('.parquet')
    if len(set(data + policy)) != len(data + policy):
        raise ImportErrorSafe('Archive contains duplicate eligible member paths')
    return data, policy, parquet


def records(stream):
    while True:
        raw = stream.readline(MAX_LINE + 1)
        if not raw:
            return
        if len(raw) > MAX_LINE:
            raise ImportErrorSafe('Input line exceeds safe size')
        try:
            row = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            row = None
        yield row, len(raw)


def archive_records(tar, archive, names):
    # libarchive expands zstd into a tar stream; tarfile preserves member boundaries.
    # Never extract paths or follow archive links on disk.
    pending = set(names)
    with tar_output(tar, ['-cf', '-', '@' + str(archive)]) as unlocked:
        try:
            with tarfile.open(fileobj=unlocked, mode='r|') as stream:
                for header in stream:
                    if header.name not in pending:
                        continue
                    if not header.isfile():
                        raise ImportErrorSafe('Listen member is not a regular file')
                    with stream.extractfile(header) as member:
                        yield from records(member)
                    pending.remove(header.name)
            while unlocked.read(65_536):
                pass
        except tarfile.TarError as exc:
            raise ImportErrorSafe('Cannot read listen archive member stream') from exc
    if pending:
        raise ImportErrorSafe('Listen member missing from archive stream')


SQL = '''CREATE TABLE listen (u BLOB NOT NULL, s TEXT NOT NULL, t INTEGER NOT NULL, a INTEGER,
    PRIMARY KEY(u,s,t)) WITHOUT ROWID'''


def init_db(db, scratch_gib=1):
    if type(scratch_gib) is not int or not 1 <= scratch_gib <= 4:
        raise ImportErrorSafe('Scratch budget must be 1–4 GiB')
    db.execute('PRAGMA journal_mode=OFF')
    db.execute('PRAGMA temp_store=MEMORY')
    page_size = db.execute('PRAGMA page_size').fetchone()[0]
    db.execute(f'PRAGMA max_page_count={scratch_gib * 1024**3 // page_size}')
    db.execute(SQL)


def ingest(db, raw, *, snapshot, secret, identity='mbid'):
    counts, lane, consumed, earliest, latest = Counter(), None, 0, None, None
    batch = []
    insert = '''INSERT INTO listen VALUES (?,?,?,?) ON CONFLICT(u,s,t) DO UPDATE SET a =
        CASE WHEN excluded.a IS NULL THEN listen.a WHEN listen.a IS NULL THEN excluded.a
        ELSE min(listen.a, excluded.a) END'''
    for row, size in raw:
        consumed += size
        if consumed > MAX_STREAM:
            raise ImportErrorSafe('Uncompressed stream limit exceeded')
        counts['input_lines'] += 1
        state, value = parse(row, snapshot=snapshot, user_field=lane, identity=identity)
        counts[state] += 1
        if value is None:
            continue
        lane, key, recording, played, inserted = value
        earliest = played if earliest is None else min(earliest, played)
        latest = played if latest is None else max(latest, played)
        counts['eligible_with_inserted_at'] += inserted is not None
        # This random-key digest is kept only in private scratch space, never in exports.
        u = hmac.digest(secret, (lane + '\0' + key).encode('utf-8', 'surrogatepass'), 'sha256')
        batch.append((u, recording, played, inserted))
        if len(batch) == 4096:
            db.executemany(insert, batch)
            batch.clear()
    db.executemany(insert, batch)
    db.commit()
    total, users, recordings = db.execute('SELECT count(*),count(DISTINCT u),count(DISTINCT s) FROM listen').fetchone()
    counts['unique_events'] = total
    counts['duplicates'] = counts['eligible'] - total
    counts['distinct_accounts'] = users
    counts['distinct_recordings'] = recordings
    counts['uncompressed_bytes_read'] = consumed
    return dict(counts), lane, earliest, latest


def check_event_budget(max_events):
    if type(max_events) is not int or not 1 <= max_events <= HARD_MAX_EVENTS:
        raise ImportErrorSafe('Export event budget out of bounds')
    return max_events


def select_dataset(db, *, train_cut=None, validation_cut=None, max_users=MAX_USERS, max_items=MAX_ITEMS,
                   identity='mbid', fixed_catalog=None, max_events=MAX_EVENTS):
    check_event_budget(max_events)
    if not 1 <= max_users <= MAX_USERS or not 1 <= max_items <= MAX_ITEMS:
        raise ImportErrorSafe('User or recording budget out of bounds')
    total = db.execute('SELECT count(*) FROM listen').fetchone()[0]
    if total < 10:
        raise ImportErrorSafe('Fewer than ten eligible unique listens')
    db.execute('CREATE INDEX time_idx ON listen(t)')
    if (train_cut is None) != (validation_cut is None):
        raise ImportErrorSafe('Supply both time boundaries or neither')
    if train_cut is None:
        train_cut, validation_cut = [db.execute('SELECT t FROM listen ORDER BY t LIMIT 1 OFFSET ?', (i,)).fetchone()[0]
                                     for i in (total * 7 // 10, total * 8 // 10)]
        if train_cut == validation_cut:
            validation_cut = db.execute('SELECT min(t) FROM listen WHERE t>?', (train_cut,)).fetchone()[0]
    if validation_cut is None or train_cut >= validation_cut:
        raise ImportErrorSafe('Timestamp ties leave an empty time partition')
    original = db.execute('SELECT sum(t<?),sum(t>=? AND t<?),sum(t>=?) FROM listen',
                          (train_cut, train_cut, validation_cut, validation_cut)).fetchone()
    if not all(original):
        raise ImportErrorSafe('There is an empty time partition')
    # When available, arrival times enforce what could have been visible. Unknown
    # arrival times are retained and the evaluation is marked as retrospective.
    where = 't < ? AND (a IS NULL OR a < ?)'
    cold_reserve = min(50, max_users // 10)
    users = [u for (u,) in db.execute(f'SELECT DISTINCT u FROM listen WHERE {where} ORDER BY u LIMIT ?',
                                    (train_cut, train_cut, max_users - cold_reserve))]
    db.execute('CREATE TEMP TABLE cohort(u BLOB PRIMARY KEY) WITHOUT ROWID')
    db.executemany('INSERT INTO cohort VALUES (?)', ((u,) for u in users))
    if fixed_catalog is None:
        items = [s for (s,) in db.execute(f'''SELECT s FROM listen JOIN cohort USING(u) WHERE {where}
                    GROUP BY s HAVING count(DISTINCT u)>=? ORDER BY count(DISTINCT u) DESC,s LIMIT ?''',
                    (train_cut, train_cut, MIN_TRAIN_LISTENERS, max_items))]
    else:
        items = tuple(fixed_catalog)
        if not 0 < len(items) <= max_items or any(mbid(s) != s for s in items) or len(set(items)) != len(items):
            raise ImportErrorSafe('Invalid fixed recording catalog')
    if not items:
        raise ImportErrorSafe('No recordings meet the training-only listener floor')
    db.execute('CREATE TEMP TABLE catalog(s TEXT PRIMARY KEY) WITHOUT ROWID')
    db.executemany('INSERT INTO catalog VALUES (?)', ((s,) for s in items))
    if fixed_catalog is not None:
        eligible = db.execute(f'''SELECT count(*) FROM (SELECT s FROM listen JOIN cohort USING(u)
                      JOIN catalog USING(s) WHERE {where} GROUP BY s HAVING count(DISTINCT u)>=?)''',
                              (train_cut, train_cut, MIN_TRAIN_LISTENERS)).fetchone()[0]
        if eligible != len(items):
            raise ImportErrorSafe('Fixed catalog does not meet the training-only listener floor')
    # Only score an extra post-cutoff cohort with no observable training history.
    # Its appearance in the holdout does not change models, profiles or catalog.
    remaining = max_users - len(users)
    cold = [u for (u,) in db.execute('''SELECT DISTINCT l.u FROM listen AS l
        WHERE l.t>=? AND NOT EXISTS (SELECT 1 FROM listen AS p WHERE p.u=l.u AND p.t<? AND (p.a IS NULL OR p.a<?))
        ORDER BY l.u LIMIT ?''', (train_cut, train_cut, train_cut, remaining))]
    db.executemany('INSERT INTO cohort VALUES (?)', ((u,) for u in cold))
    user_ids = {u: i for i, u in enumerate(users + cold, 1)}
    item_ids = {s: i for i, s in enumerate(sorted(items), 1)}
    partitions = {'train': [], 'validation': [], 'test': []}
    known_prior = set()
    query = '''SELECT u,s,t,a FROM listen JOIN cohort USING(u) JOIN catalog USING(s)
               WHERE t>=? OR a IS NULL OR a<? ORDER BY t,u,s LIMIT ?'''
    for index, (u, recording, t, a) in enumerate(db.execute(query, (train_cut, train_cut, max_events + 1))):
        if index >= max_events:
            raise ImportErrorSafe('Export event budget exceeded; reduce the cohort or calendar window')
        uid, sid = user_ids[u], item_ids[recording]
        name = 'train' if t < train_cut else 'validation' if t < validation_cut else 'test'
        if name == 'train':
            known_prior.add((uid, sid))
        partitions[name].append({'user_id': uid, 'song_id': sid, 'occurred_at': timestamp(t), 'kind': 'LISTEN', 'positive': True})
    excluded = {}
    for name, filt, params in (('validation','t>=? AND t<?',(train_cut,validation_cut)), ('test','t>=?',(validation_cut,))):
        pairs, affected = db.execute(f'''SELECT count(*),count(DISTINCT u) FROM (
            SELECT DISTINCT u,s FROM listen JOIN cohort USING(u) WHERE {filt} AND s NOT IN (SELECT s FROM catalog)
            AND NOT EXISTS (SELECT 1 FROM listen p WHERE p.u=listen.u AND p.s=listen.s AND p.t<? AND (p.a IS NULL OR p.a<?)))''',
            (*params, train_cut, train_cut)).fetchone()
        excluded[name] = {'out_of_catalog_new_pairs': pairs, 'affected_users': affected}
    return {'songs': [{'song_id': i, 'recording_' + identity: s, 'tag_ids': []} for s, i in item_ids.items()],
            'users': [{'user_id': uid} for uid in user_ids.values()], 'partitions': partitions}, {
        'train_cut': timestamp(train_cut), 'validation_cut': timestamp(validation_cut),
        'all_eligible_partition_counts': dict(zip(partitions, original)), 'exports': {k: len(v) for k,v in partitions.items()},
        'training_account_pool_sample': len(users), 'zero_observable_history_sample': len(cold),
        'excluded_targets': excluded, 'train_pairs': len(known_prior),
        'train_late_submissions_excluded': db.execute('SELECT count(*) FROM listen WHERE t<? AND a>=?', (train_cut, train_cut)).fetchone()[0],
    }


def run(archive, checksum, output, *, source_url, downloaded_at, snapshot_at, secret_path, max_users=MAX_USERS,
        max_items=MAX_ITEMS, tar_exe=None, identity='mbid', scratch_gib=1,
        fixed_catalog_manifest=None, max_events=MAX_EVENTS):
    check_event_budget(max_events)
    if identity not in IDENTITIES:
        raise ImportErrorSafe('Unknown recording identity mode')
    archive, output = Path(archive).resolve(), Path(output).resolve()
    if output.exists():
        raise ImportErrorSafe('Output directory already exists')
    if type(scratch_gib) is not int or not 1 <= scratch_gib <= 4:
        raise ImportErrorSafe('Scratch budget must be 1–4 GiB')
    if shutil.disk_usage(output.parent).free < (scratch_gib + 1) * 1024**3:
        raise ImportErrorSafe('Insufficient free space for requested scratch budget')
    if archive.stat().st_size > MAX_ARCHIVE:
        raise ImportErrorSafe('Archive exceeds approved local budget')
    with Path(checksum).open('rb') as stream:
        expected = stream.read(1025).strip().decode('ascii')
    measured = digest(archive)
    if not re.fullmatch('[0-9a-fA-F]{64}', expected) or expected.lower() != measured:
        raise ImportErrorSafe('Archive SHA-256 does not match')
    fixed = {}
    if fixed_catalog_manifest is not None:
        baseline_path = Path(fixed_catalog_manifest)
        with baseline_path.open('rb') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ImportErrorSafe('Fixed catalog manifest exceeds size limit')
        baseline = json.loads(raw)
        if (baseline['schema'] != SCHEMA or baseline['origin'] != 'REAL' or baseline['archive_sha256'] != measured
                or baseline.get('recording_id_kind', 'mbid') != identity or baseline['data_file'] != 'data.json'
                or epoch(baseline['archive_snapshot_at']) != epoch(snapshot_at)):
            raise ImportErrorSafe('Fixed catalog must use the same archive, snapshot and recording identity')
        baseline_data = baseline_path.parent / 'data.json'
        if baseline_data.is_symlink():
            raise ImportErrorSafe('Fixed catalog data must be a local regular file')
        with baseline_data.open('rb') as stream:
            raw = stream.read(MAX_DATA_BYTES + 1)
        if len(raw) > MAX_DATA_BYTES or hashlib.sha256(raw).hexdigest() != baseline['data_sha256']:
            raise ImportErrorSafe('Fixed catalog data integrity check failed')
        fixed = {'train_cut': epoch(baseline['split']['train_cut']),
                 'validation_cut': epoch(baseline['split']['validation_cut']),
                 'fixed_catalog': [row['recording_' + identity] for row in json.loads(raw)['songs']]}
        del raw
    snapshot = epoch(snapshot_at)
    datetime.fromisoformat(downloaded_at.replace('Z', '+00:00')).utcoffset() is not None or (_ for _ in ()).throw(ImportErrorSafe('Download timestamp must include time zone'))
    tar = tar_exe or shutil.which('tar.exe') or shutil.which('tar')
    if not tar:
        raise ImportErrorSafe('Existing tar executable not found')
    names, policies, parquet = members(tar, archive)
    if not names:
        raise ImportErrorSafe('PARQUET_ONLY: no eligible JSONL members' if parquet else 'No eligible JSONL members')
    license_in_archive = False
    archive_metadata = {}
    for name in policies:
        field = PurePosixPath(name).name
        if field in {'COPYING', 'LICENSE', 'LICENSE.txt'}:
            with tar_output(tar, ['-xOf', str(archive), '--', name]) as stream:
                license_text = stream.read(65537)
                if len(license_text) > 65536:
                    raise ImportErrorSafe('Archive license member exceeds limit')
                text = license_text.lower()
                if not any(v in text for v in (b'creativecommons.org/publicdomain/zero/1.0', b'cc0 1.0 universal')):
                    raise ImportErrorSafe('Archive license does not explicitly identify CC0')
                license_in_archive = True
        else:
            with tar_output(tar, ['-xOf', str(archive), '--', name]) as stream:
                raw = stream.read(257)
                if len(raw) > 256 or field in archive_metadata:
                    raise ImportErrorSafe('Oversized or duplicate archive metadata')
            value = raw.decode('ascii').strip()
            if field == 'SCHEMA_SEQUENCE':
                if not re.fullmatch(r'[0-9]{1,9}', value):
                    raise ImportErrorSafe('Invalid archive schema sequence')
                archive_metadata[field] = int(value)
            else:
                reported = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if reported.utcoffset() is None:
                    raise ImportErrorSafe('Archive metadata timestamp must include time zone')
                archive_metadata[field] = reported.astimezone(timezone.utc).isoformat()
    start, end = archive_metadata.get('START_TIMESTAMP'), archive_metadata.get('END_TIMESTAMP')
    if start and end and datetime.fromisoformat(start) >= datetime.fromisoformat(end):
        raise ImportErrorSafe('Invalid archive ingestion interval')
    secret_path = Path(secret_path)
    if not secret_path.exists():
        with secret_path.open('xb') as stream:
            stream.write(secrets.token_bytes(32))
    with secret_path.open('rb') as stream:
        secret = stream.read(33)
    if len(secret) != 32:
        raise ImportErrorSafe('Invalid private sampling key')

    with tempfile.TemporaryDirectory(prefix='temp_lb_', dir=output.parent) as scratch:
        from contextlib import closing
        with (closing(sqlite3.connect(Path(scratch) / 'private.sqlite3')) as db,
              closing(archive_records(tar, archive, names)) as raw):
            init_db(db, scratch_gib)
            try:
                counts, lane, first, last = ingest(db, raw, snapshot=snapshot, secret=secret, identity=identity)
                data, split = select_dataset(db, max_users=max_users, max_items=max_items, identity=identity,
                                             max_events=max_events, **fixed)
            except sqlite3.Error as exc:
                if getattr(exc, 'sqlite_errorcode', None) == sqlite3.SQLITE_FULL:
                    raise ImportErrorSafe('Scratch SQLite reached its disk budget') from exc
                raise
    output.mkdir(exist_ok=False)
    data_path = output / 'data.json'
    write_json(data_path, data)
    manifest = {'schema': SCHEMA, 'origin': 'REAL', 'source': 'ListenBrainz', 'archive_name': archive.name,
                'source_url': source_url, 'archive_bytes': archive.stat().st_size, 'archive_sha256': measured,
                'downloaded_at': downloaded_at, 'archive_snapshot_at': snapshot_at,
                 'archive_metadata': archive_metadata,
                'license': 'CC0-1.0', 'license_url': 'https://metabrainz.org/datasets/postgres-dumps',
                'archive_cc0_marker_confirmed': license_in_archive, 'timezone': 'UTC',
                'timestamp_origin': 'Listen event time: archive timestamp or API listened_at', 'identity_field': lane,
                 'recording_id_kind': identity,
                'recording_identity': ('MessyBrainz recording MSID; not a MusicBrainz MBID' if identity == 'msid'
                                        else 'resolved MusicBrainz recording MBID only; client conflicts excluded'),
                'feedback': 'binary implicit LISTEN, no observed negatives', 'sampling': 'private HMAC bottom-k by account',
                'max_users': max_users, 'max_items': max_items, 'min_train_listeners': MIN_TRAIN_LISTENERS,
                'scratch_limit_gib': scratch_gib, 'input': counts, 'jsonl_members': len(names), 'event_time_range': [timestamp(first), timestamp(last)],
                'split': split, 'data_file': 'data.json', 'data_sha256': digest(data_path)}
    manifest['max_events'] = max_events
    if fixed:
        manifest['fixed_catalog_baseline_data_sha256'] = baseline['data_sha256']
    write_json(output / 'manifest.json', manifest)
    return manifest


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'checksum', 'output', 'source-url', 'downloaded-at', 'snapshot-at', 'secret-path'):
        cli.add_argument('--' + name, required=True)
    cli.add_argument('--identity', choices=IDENTITIES, default='mbid')
    cli.add_argument('--max-users', type=int, default=MAX_USERS)
    cli.add_argument('--max-items', type=int, default=MAX_ITEMS)
    cli.add_argument('--scratch-gib', type=int, choices=range(1, 5), default=1)
    cli.add_argument('--max-events', type=int, default=MAX_EVENTS)
    cli.add_argument('--fixed-catalog-manifest')
    args = cli.parse_args()
    try:
        summary = run(**vars(args))
    except ImportErrorSafe as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, KeyError, TypeError, ValueError, sqlite3.Error):
        print('Import failed: local I/O, time format, or resource budget error', file=sys.stderr)
        return 2
    print(json.dumps({'input': summary['input'], 'split': summary['split']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
