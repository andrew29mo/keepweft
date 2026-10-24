"""Online backup and a fixed, versioned ledger application contract."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
from urllib.parse import quote

PROFILE = 'ledger-v1'

class Refused(Exception):
    pass


def runtime():
    v = sqlite3.sqlite_version_info
    if not (v >= (3, 51, 3) or v[:2] == (3, 50) and v >= (3, 50, 7) or v[:2] == (3, 44) and v >= (3, 44, 6)):
        raise Refused('SQLite WAL-reset fix not qualified in this runtime')
    with sqlite3.connect(':memory:') as c:
        return dict(python_sqlite=sqlite3.sqlite_version,
                    source_id=c.execute('select sqlite_source_id()').fetchone()[0],
                    compile_options=[r[0] for r in c.execute('pragma compile_options')])


def regular(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise Refused('Expected an existing regular file')
    for parent in path.absolute().parents:
        if parent.is_symlink():
            raise Refused('Symlink ancestor rejected')
    return path


def readonly(path):
    path = regular(path)
    return sqlite3.connect('file:' + quote(str(path.resolve()), safe='/') + '?mode=ro&cache=private',
                           uri=True, isolation_level=None, timeout=0.05)


def digest_file(path):
    h = hashlib.sha256()
    with regular(path).open('rb') as f:
        for block in iter(lambda: f.read(65536), b''):
            h.update(block)
    return h.hexdigest()


def dump(path, value):
    path = Path(path)
    with path.open('x') as f:
        json.dump(value, f, sort_keys=True, allow_nan=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def init_ledger(path, count=0, payload_size=2048):
    path = Path(path)
    if path.exists():
        raise Refused('Source already exists')
    c = sqlite3.connect(path, isolation_level=None)
    c.execute('pragma journal_mode=wal')
    c.execute('pragma synchronous=full')
    c.executescript('''pragma user_version=1;
        create table meta(uuid text not null);
        create table tx(seq integer primary key, payload blob not null, digest text not null);
        create table item(seq integer references tx(seq), part integer, primary key(seq,part));''')
    identity = uuid.uuid4().hex
    c.execute('insert into meta values(?)', (identity,))
    for seq in range(1, count + 1):
        append(c, seq, payload_size)
    c.close()
    return identity


def append(c, seq, payload_size=2048):
    payload = (hashlib.sha256(str(seq).encode()).digest() * ((payload_size + 31) // 32))[:payload_size]
    began = time.monotonic()
    c.execute('begin immediate')
    try:
        c.execute('insert into tx values(?,?,?)', (seq, payload, hashlib.sha256(payload).hexdigest()))
        c.executemany('insert into item values(?,?)', ((seq, 0), (seq, 1)))
        c.execute('commit')
    except BaseException:
        c.execute('rollback')
        raise
    return time.monotonic() - began


def inspect(c, expected_uuid, guard=lambda: None):
    guard()
    if c.execute('pragma user_version').fetchone() != (1,):
        raise Refused('Wrong application schema version')
    if c.execute('select uuid from meta').fetchall() != [(expected_uuid,)]:
        raise Refused('Wrong database identity')
    if c.execute('pragma integrity_check').fetchall() != [('ok',)]:
        raise Refused('SQLite integrity check failed')
    if c.execute('pragma foreign_key_check').fetchall():
        raise Refused('Foreign key violation')
    h = hashlib.sha256()
    n = 0
    for seq, payload, digest in c.execute('select seq,payload,digest from tx order by seq'):
        guard()
        n += 1
        if seq != n or hashlib.sha256(payload).hexdigest() != digest:
            raise Refused('Invalid ledger sequence/content')
        h.update(seq.to_bytes(8, 'big') + len(payload).to_bytes(8, 'big') + payload)
    # SQLite permits NULL child keys even with a declared FK, and an unknown
    # schema may omit the FK entirely. Validate the application's actual relation
    # independently: row counts/group shape alone do not prove parent membership.
    if c.execute('select 1 from item left join tx on item.seq=tx.seq where tx.seq is null limit 1').fetchone():
        raise Refused('Transaction item parent mismatch')
    if c.execute('select count(*) from item').fetchone()[0] != n * 2:
        raise Refused('Missing transaction items')
    if c.execute('select seq from item group by seq having count(*) != 2 or min(part) != 0 or max(part) != 1').fetchone():
        raise Refused('Wrong transaction items')
    return dict(profile=PROFILE, uuid=expected_uuid, count=n, max_seq=n, content_sha256=h.hexdigest())


def checkpoint(directory, name, deadline):
    """Explicit test-only scheduling barrier; never supplies successful product results."""
    if directory is None:
        return
    directory = Path(directory)
    if not (directory / (name + '.arm')).exists():
        return
    (directory / (name + '.seen')).write_text(str(os.getpid()))
    while not (directory / (name + '.release')).exists():
        if time.monotonic() >= deadline:
            raise TimeoutError('Fault barrier deadline')
        time.sleep(.01)


def copy_snapshot(source, stage, expected_uuid, deadline, max_bytes, wal_growth_limit,
                  barriers=None, cancelled=lambda: False):
    runtime()
    stage = Path(stage)
    source = regular(source)
    before = source.stat()
    wal = Path(str(source) + '-wal')
    initial_wal = wal.stat().st_size if wal.exists() else 0
    def guard():
        if cancelled():
            raise InterruptedError('Cancelled')
        if time.monotonic() >= deadline:
            raise TimeoutError('Backup deadline')
        if wal.exists() and wal.stat().st_size - initial_wal > wal_growth_limit:
            raise Refused('Source WAL growth budget exceeded')
    src = readonly(source)
    dst = None
    try:
        src.set_progress_handler(lambda: (guard(), 0)[1], 1000)
        src.execute('begin')
        # First read establishes the WAL read snapshot, not BEGIN alone.
        if src.execute('select uuid from meta').fetchall() != [(expected_uuid,)]:
            raise Refused('Wrong database identity')
        established = time.monotonic()
        checkpoint(barriers, 'snapshot_open', deadline)
        expected = inspect(src, expected_uuid, guard)
        pages = src.execute('pragma page_count').fetchone()[0]
        page_size = src.execute('pragma page_size').fetchone()[0]
        if pages * page_size > max_bytes:
            raise Refused('Snapshot exceeds artifact limit')
        dst = sqlite3.connect(stage / 'db.sqlite', isolation_level=None, timeout=.05)
        dst.execute('pragma journal_mode=delete')
        def progress(status, remaining, total):
            guard()
            if total * page_size > max_bytes:
                raise Refused('Snapshot grew beyond artifact limit')
        src.backup(dst, pages=32, progress=progress, sleep=.01)
        src.execute('rollback')
        src.close()
        src = None
        dst.execute('pragma journal_mode=delete')
        # Deliberately before close: takeover must not publish this inode yet.
        checkpoint(barriers, 'copy_complete', deadline)
        dst.close()
        dst = None
        guard()
        after = source.stat()
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise Refused('Source path identity changed')
        result = dict(expected=expected, snapshot_established=established,
                      completed=time.monotonic(), bytes=(stage/'db.sqlite').stat().st_size)
        dump(stage / 'result.json', result)
        sync_dir(stage)
        return result
    finally:
        if dst is not None:
            dst.close()
        if src is not None:
            src.close()


def verify_closed(directory, expected, max_bytes, deadline):
    directory = Path(directory)
    def guard():
        if time.monotonic() >= deadline:
            raise TimeoutError('Verification deadline')
    for p in directory.iterdir():
        if p.is_symlink() or not p.is_file() or p.name not in ('db.sqlite','result.json','manifest.json'):
            raise Refused('Unexpected artifact/sidecar')
    if regular(directory/'db.sqlite').stat().st_size > max_bytes:
        raise Refused('Artifact too large')
    with contextlib.closing(readonly(directory/'db.sqlite')) as c:
        c.set_progress_handler(lambda: (guard(), 0)[1], 1000)
        actual = inspect(c, expected['uuid'], guard)
    if actual != expected:
        raise Refused('Snapshot boundary/content mismatch')
    guard()
    return dict(profile=PROFILE, expected=expected, bytes=(directory/'db.sqlite').stat().st_size,
                sha256=digest_file(directory/'db.sqlite'))
