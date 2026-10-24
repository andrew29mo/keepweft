"""Single-writer controller. All mutation/recovery paths share this implementation."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from urllib.parse import quote
from .data import (Refused, runtime, regular, readonly, dump, digest_file, sync_dir,
                   verify_closed, checkpoint)

class Busy(Refused):
    pass

class Degraded(Refused):
    pass

DEFAULTS = dict(budget_bytes=64*1024*1024, artifact_bytes=8*1024*1024,
                wal_growth_bytes=32*1024*1024, headroom_bytes=1024*1024,
                keep=2, max_receipts=128, catalog_pages=2048)


def usage(root):
    logical = allocated = 0
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            p = Path(base)/name
            if p.is_symlink():
                raise Degraded('Unexpected symlink in managed store')
        for name in files:
            s = (Path(base)/name).stat()
            logical += s.st_size
            allocated += s.st_blocks*512
    s = os.statvfs(root)
    return dict(logical_bytes=logical, allocated_bytes=allocated,
                filesystem_free_bytes=s.f_bavail*s.f_frsize)


def worker_error(stage, stderr):
    # The durable error file itself may be empty/partial under ENOSPC. Prefer
    # the bounded pipe, preserving the actual storage error rather than JSONDecodeError.
    candidates=[stderr]
    try:candidates.append((Path(stage)/'error.json').read_text())
    except OSError:pass
    for text in candidates:
        try:
            value=json.loads(text)
            if isinstance(value,dict) and isinstance(value.get('error'),str):return value
        except (ValueError,TypeError):pass
    return dict(error='Worker failed without a complete error receipt',sqlite_errorcode=None)


class Controller:
    def __init__(self, root, source=None, expected_uuid=None, options=None, barriers=None):
        runtime()
        self.root = Path(root).absolute()
        if self.root.is_symlink() or any(p.is_symlink() for p in self.root.parents):
            raise Refused('Symlink store rejected')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.stat().st_uid != os.getuid() or self.root.stat().st_mode & 0o077:
            raise Refused('Store must be owner-only')
        self.fd = os.open(self.root/'.lock', os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW, 0o600)
        self.db = None
        self.barriers = barriers
        self.blocked = False
        self.progress = lambda: None
        self.cancelled = lambda: False
        try:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Busy('Prior controller/worker still owns store') from exc
            catalog = self.root/'catalog.sqlite'
            fresh = not catalog.exists()
            if fresh:
                if any(p.name != '.lock' for p in self.root.iterdir()):
                    raise Degraded('Missing catalog with existing inventory; no automatic reconstruction')
                if source is None or expected_uuid is None:
                    raise Refused('Fresh store requires registered source and identity')
                source = regular(source).resolve()
                if source.is_relative_to(self.root):
                    raise Refused('Source must be outside managed store')
                cfg = dict(DEFAULTS, **(options or {}), source=str(source), uuid=expected_uuid)
                if cfg['keep'] < 2 or cfg['artifact_bytes'] <= 0 or cfg['max_receipts'] < 1:
                    raise Refused('Invalid limits')
                for name in ('staging','backups','restores'):
                    (self.root/name).mkdir(mode=0o700)
                self.db = sqlite3.connect(catalog, isolation_level=None)
                self.db.execute('pragma journal_mode=delete')
                self.db.execute('pragma synchronous=full')
                self.db.executescript('''create table authority(id integer primary key, epoch integer, revision integer, config text);
                    create table ops(id text primary key, epoch integer, kind text, state text, details text);
                    create table backups(id text primary key, manifest text, state text, pins integer);
                    create table restores(id text primary key, backup_id text, state text, manifest text);''')
                self.db.execute('insert into authority values(1,0,0,?)', (json.dumps(cfg),))
                sync_dir(self.root)
            else:
                regular(catalog)
                self.db = sqlite3.connect('file:'+quote(str(catalog),safe='/')+'?mode=rw', uri=True, isolation_level=None)
                self.db.execute('pragma synchronous=full')
                if self.db.execute('pragma integrity_check').fetchall() != [('ok',)]:
                    raise Degraded('Catalog integrity failure')
                cfg = json.loads(self.db.execute('select config from authority where id=1').fetchone()[0])
                if source is not None and str(regular(source).resolve()) != cfg['source']:
                    raise Refused('Registered source path changed')
                if expected_uuid is not None and expected_uuid != cfg['uuid']:
                    raise Refused('Registered source identity changed')
                if options and any(cfg.get(k) != v for k,v in options.items()):
                    raise Refused('Implicit policy change rejected')
            self.cfg = cfg
            self.db.execute('pragma max_page_count='+str(cfg['catalog_pages']))
            with self.tx():
                self.db.execute('update authority set epoch=epoch+1, revision=revision+1 where id=1')
            self.recover()
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        if getattr(self, 'fd', None) is not None:
            # Never LOCK_UN: inherited worker descriptors must retain the lock.
            os.close(self.fd)
            self.fd = None

    @contextlib.contextmanager
    def tx(self):
        try:
            self.db.execute('begin immediate')
            yield
            self.db.execute('commit')
        except BaseException as exc:
            if isinstance(exc,(sqlite3.Error,OSError)):self.blocked=True
            if self.db.in_transaction:
                try:self.db.execute('rollback')
                except sqlite3.Error:self.blocked=True
            raise

    @property
    def token(self):
        return dict(zip(('epoch','revision'), self.db.execute('select epoch,revision from authority where id=1').fetchone()))

    def _check(self, token):
        if self.blocked:
            raise Degraded('Unreconciled occupancy; explicit repair/restart required')
        if token is not None and token != self.token:
            raise Refused('Stale operation token')

    def _revision(self):
        self.db.execute('update authority set revision=revision+1 where id=1')

    def _receipt_room(self):
        if self.db.execute('select count(*) from ops').fetchone()[0] >= self.cfg['max_receipts']:
            raise Refused('Receipt capacity exhausted; no silent dedup eviction')

    def _new(self, kind, details, token=None):
        self._check(token)
        self._receipt_room()
        ident = uuid.uuid4().hex
        with self.tx():
            self.db.execute('insert into ops values(?,?,?,?,?)', (ident,self.token['epoch'],kind,'RESERVED',json.dumps(details)))
            self._revision()
        return ident

    def _phase(self, ident, state, details=None):
        with self.tx():
            old = self.db.execute('select epoch,details from ops where id=?',(ident,)).fetchone()
            if old is None or old[0] != self.token['epoch']:
                raise Refused('Retired attempt')
            if details is not None:
                details=dict(details)
                details.setdefault('retention_deleted',json.loads(old[1]).get('retention_deleted',[]))
                details.setdefault('retention_planned',json.loads(old[1]).get('retention_planned',[]))
            self.db.execute('update ops set state=?,details=? where id=?',(state,json.dumps(details) if details is not None else old[1],ident))
            self._revision()

    def status(self):
        return dict(token=self.token, usage=usage(self.root), blocked=self.blocked,
                    operations=[dict(id=i,kind=k,state=s,details=json.loads(d)) for i,k,s,d in self.db.execute('select id,kind,state,details from ops order by rowid')],
                    backups=[dict(id=i,state=s,pins=p,manifest=json.loads(m)) for i,m,s,p in self.db.execute('select id,manifest,state,pins from backups order by rowid')],
                    restores=[dict(id=i,backup_id=b,state=s) for i,b,s in self.db.execute('select id,backup_id,state from restores')])

    def _reserve(self):
        self._check(None)
        u = usage(self.root)
        reserve = self.cfg['artifact_bytes']*2 + self.cfg['headroom_bytes']
        if u['logical_bytes'] + reserve > self.cfg['budget_bytes'] or u['filesystem_free_bytes'] < reserve:
            raise Refused('Capacity unavailable; previous backups preserved')
        return reserve

    def _barrier(self, name, deadline):
        if self.barriers is None:
            return
        p = Path(self.barriers)
        if not (p/(name+'.arm')).exists():return
        (p/(name+'.seen')).write_text(str(os.getpid()))
        while not (p/(name+'.release')).exists():
            self.progress()
            if name not in ('publish_intent','after_rename','after_catalog') and self.cancelled():
                raise InterruptedError('CANCELLED')
            if time.monotonic() >= deadline:raise TimeoutError('Fault barrier deadline')
            time.sleep(.01)

    def _directory(self, area, ident):
        if len(ident) != 32 or any(c not in '0123456789abcdef' for c in ident):
            raise Refused('Invalid object identity')
        p = self.root/area/ident
        if (self.root/area).is_symlink() or p.is_symlink():
            raise Degraded('Unexpected object symlink')
        return p

    def _worker(self, ident, deadline, cancel_path=None):
        stage = self._directory('staging',ident)
        job = dict(source=self.cfg['source'],expected_uuid=self.cfg['uuid'],stage=str(stage),
                   deadline=deadline,max_bytes=self.cfg['artifact_bytes'],wal_growth_limit=self.cfg['wal_growth_bytes'],
                   barriers=str(self.barriers) if self.barriers else None,
                   cancel_path=str(cancel_path) if cancel_path else None,lock_fd=self.fd)
        dump(stage/'job.json', job)
        # exec, no SQLite connection inherited. FD explicitly retains the OFD lock.
        self._phase(ident,'COPYING',dict(reserved=self.cfg['artifact_bytes']*2+self.cfg['headroom_bytes']))
        proc = subprocess.Popen([sys.executable,'-m','keepweft.worker',str(stage/'job.json')],
                                pass_fds=(self.fd,), start_new_session=True,
                                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        reason = None
        try:
            while proc.poll() is None:
                self.progress()
                if self.cancelled():reason = 'CANCELLED'
                if cancel_path and Path(cancel_path).exists():
                    reason = 'CANCELLED'
                if time.monotonic() >= deadline:
                    reason = reason or 'FAILED_TIMEOUT'
                if reason:
                    proc.terminate()
                    break
                time.sleep(.01)
        except BaseException:
            if proc.poll() is None:proc.terminate()
            reason = 'FAILED_CONTROLLER_INTERRUPTED'
        if proc.poll() is None:
            try:proc.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:proc.wait(timeout=.5)
                except subprocess.TimeoutExpired:
                    self._phase(ident,'CLEANUP_PENDING',dict(reason=reason,reserved=job['max_bytes']*2+self.cfg['headroom_bytes']))
                    self.blocked = True
                    raise Degraded('Worker exit unknown; reservation retained')
        stderr=proc.stderr.read(4096);proc.stderr.close()
        if reason:
            raise InterruptedError(reason)
        if proc.returncode:
            error=worker_error(stage,stderr)
            refused=Refused(error['error'])
            refused.sqlite_errorcode=error.get('sqlite_errorcode')
            raise refused
        # Publication cannot race a live writer holding db.sqlite open.
        return json.loads((stage/'result.json').read_text())

    def backup(self, token=None, timeout=10., cancel_path=None, operation_id=None):
        self._check(token)
        if not 0 < timeout <= 60:
            raise Refused('Deadline must be in (0,60] seconds')
        # Predictable refusals must happen before retention can delete anything.
        if operation_id is None:
            self._receipt_room()
            reserved = self._reserve()
            ident = self._new('backup',dict(reserved=reserved))
        else:
            ident = operation_id
            row = self.db.execute('select epoch,kind,state from ops where id=?',(ident,)).fetchone()
            if row != (self.token['epoch'],'backup','QUEUED'):
                raise Refused('Operation not dispatchable')
            reserved = 0
        stage = self._directory('staging',ident)
        deadline = time.monotonic()+timeout
        deleted = []
        try:
            self.progress()
            if self.cancelled() or (cancel_path and Path(cancel_path).exists()):
                raise InterruptedError('CANCELLED')
            reserved = self._reserve()
            self._phase(ident,'RESERVED',dict(reserved=reserved))
            before = {r[0] for r in self.db.execute("select id from backups where state='AVAILABLE'")}
            try:self.prune(need_slot=True,operation_id=ident)
            finally:
                # Leaving AVAILABLE may only mean a failed DELETING intent.
                # Completion requires both filesystem sync and the DELETED commit.
                deleted = sorted(bid for bid in before if self.db.execute("select state from backups where id=?",(bid,)).fetchone()==('DELETED',))
            self._phase(ident,'RESERVED',dict(reserved=reserved,retention_deleted=deleted))
            self._barrier('admitted',deadline)
            stage.mkdir(mode=0o700)
            result = self._worker(ident,deadline,cancel_path)
            (stage/'job.json').unlink()
            self._phase(ident,'SEALED')
            manifest = verify_closed(stage,result['expected'],self.cfg['artifact_bytes'],deadline)
            manifest.update(id=ident,epoch=self.token['epoch'],attempt=ident,
                            snapshot_established=result['snapshot_established'],copy_completed=result['completed'])
            if usage(self.root)['logical_bytes'] > self.cfg['budget_bytes']:
                raise Refused('Managed soft quota exceeded')
            dump(stage/'manifest.json',manifest)
            for p in stage.iterdir():
                fd = os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
                try:os.fsync(fd)
                finally:os.close(fd)
            sync_dir(stage)
            self._barrier('before_publish',deadline)
            self.progress()
            if self.cancelled() or (cancel_path and Path(cancel_path).exists()):
                raise InterruptedError('CANCELLED')
            if time.monotonic() >= deadline:raise TimeoutError('Backup deadline before publication')
            # No event pump between the cancellation check and durable intent.
            self._phase(ident,'PUBLISHING',dict(manifest=manifest,reserved=reserved,retention_deleted=deleted))
            self._barrier('publish_intent',deadline)
            final = self._directory('backups',ident)
            if final.exists():
                raise Degraded('Final object already exists')
            stage.rename(final)
            sync_dir(final.parent)
            sync_dir(stage.parent)
            self._barrier('after_rename',deadline)
            with self.tx():
                self.db.execute('insert into backups values(?,?,?,0)',(ident,json.dumps(manifest),'AVAILABLE'))
                self.db.execute('update ops set state=?,details=? where id=?',('AVAILABLE',json.dumps(dict(manifest=manifest,reserved=0,retention_deleted=deleted)),ident))
                self._revision()
            self._barrier('after_catalog',deadline)
            return manifest
        except BaseException as exc:
            state = self.db.execute('select state from ops where id=?',(ident,)).fetchone()[0]
            # Ambiguous publication/storage failures stay recoverable, never erased.
            if state not in ('PUBLISHING','AVAILABLE','CLEANUP_PENDING'):
                try:
                    self._phase(ident,'CLEANUP_PENDING',dict(error=type(exc).__name__+': '+str(exc),reserved=reserved,retention_deleted=deleted))
                    if stage.exists():shutil.rmtree(stage);sync_dir(stage.parent)
                    self._phase(ident,'CANCELLED' if isinstance(exc,InterruptedError) and str(exc)=='CANCELLED' else 'FAILED',dict(error=type(exc).__name__+': '+str(exc),reserved=0,retention_deleted=deleted))
                except BaseException:
                    self.blocked = True
            if isinstance(exc,(sqlite3.Error,OSError)) or state in ('PUBLISHING','CLEANUP_PENDING'):
                self.blocked = True
            raise

    def _validated(self, bid, deadline):
        row = self.db.execute('select manifest,state from backups where id=?',(bid,)).fetchone()
        if row is None or row[1] != 'AVAILABLE':raise Refused('Backup unavailable')
        m = json.loads(row[0]);p = self._directory('backups',bid)
        if json.loads((p/'manifest.json').read_text()) != m:
            raise Degraded('Manifest/catalog disagreement')
        if verify_closed(p,m['expected'],self.cfg['artifact_bytes'],deadline)['sha256'] != m['sha256']:
            raise Degraded('Backup hash mismatch')
        return m,p

    def restore(self, bid, token=None, timeout=10.):
        self._check(token)
        if self.db.execute("select count(*) from restores where state!='RELEASED'").fetchone()[0]:
            raise Refused('One restored instance limit')
        reserved = self._reserve();deadline=time.monotonic()+timeout
        m,origin=self._validated(bid,deadline)
        ident=self._new('restore',dict(backup_id=bid,reserved=reserved))
        target=self._directory('restores',ident)
        with self.tx():
            self.db.execute('update backups set pins=pins+1 where id=?',(bid,))
            self.db.execute('insert into restores values(?,?,?,?)',(ident,bid,'MATERIALIZING',json.dumps(m)))
            self._revision()
        target.mkdir(mode=0o700)
        try:
            shutil.copyfile(origin/'db.sqlite',target/'db.sqlite')
            actual=verify_closed(target,m['expected'],self.cfg['artifact_bytes'],deadline)
            if actual['sha256'] != m['sha256']:raise Refused('Restore hash mismatch')
            dump(target/'manifest.json',m);sync_dir(target)
            self._barrier('restore_materialized',deadline)
            # This fixed application query is the same contract served by view.py.
            with contextlib.closing(readonly(target/'db.sqlite')) as c:observed=c.execute('select count(*),coalesce(max(seq),0) from tx').fetchone()
            if observed != (m['expected']['count'],m['expected']['max_seq']):raise Refused('Application query mismatch')
            with self.tx():
                self.db.execute("update restores set state='READY' where id=?",(ident,))
                self.db.execute("update ops set state='READY',details=? where id=?",(json.dumps(dict(backup_id=bid,reserved=0)),ident))
                self._revision()
            return dict(id=ident,backup_id=bid,expected=m['expected'],path=str(target/'db.sqlite'))
        except BaseException:
            self.blocked=True
            raise

    def release(self, ident, token=None):
        self._check(token)
        row=self.db.execute('select backup_id,state from restores where id=?',(ident,)).fetchone()
        if row is None or row[1]=='RELEASED':raise Refused('Restore unavailable')
        with self.tx():
            self.db.execute("update restores set state='RELEASING' where id=?",(ident,));self._revision()
        p=self._directory('restores',ident)
        if p.exists():shutil.rmtree(p);sync_dir(p.parent)
        with self.tx():
            self.db.execute("update restores set state='RELEASED' where id=?",(ident,))
            self.db.execute('update backups set pins=pins-1 where id=? and pins>0',(row[0],));self._revision()

    def delete(self, bid, token=None, deadline=None):
        self._check(token);deadline=deadline or time.monotonic()+10
        row=self.db.execute('select pins,state from backups where id=?',(bid,)).fetchone()
        if row is None or row != (0,'AVAILABLE'):raise Refused('Pinned/unavailable backup')
        available=self.db.execute("select id from backups where state='AVAILABLE' order by rowid").fetchall()
        # Most recently validated backup is conservatively protected.
        if len(available)<=1 or available[-1][0]==bid:raise Refused('Last/latest usable backup protected')
        with self.tx():
            self.db.execute("update backups set state='DELETING' where id=?",(bid,));self._revision()
        self._barrier('delete_intent',deadline)
        p=self._directory('backups',bid)
        if p.exists():shutil.rmtree(p)
        sync_dir(p.parent)
        self._barrier('after_unlink',deadline)
        with self.tx():
            self.db.execute("update backups set state='DELETED' where id=?",(bid,));self._revision()

    def prune(self, token=None, need_slot=False, operation_id=None):
        self._check(token)
        rows=self.db.execute("select id,pins from backups where state='AVAILABLE' order by rowid").fetchall()
        desired=self.cfg['keep']-(1 if need_slot else 0)
        while len(rows)>desired:
            eligible=[i for i,p in rows[:-1] if p==0]
            if not eligible:raise Refused('Retention blocked by pins/latest backup')
            candidate=eligible[0]
            if operation_id is not None:
                # Persist attribution before deletion; recovery can derive actual
                # effects even if the owner dies before its in-memory diff is saved.
                row=self.db.execute('select details from ops where id=?',(operation_id,)).fetchone()
                details=json.loads(row[0]);planned=details.setdefault('retention_planned',[])
                if candidate not in planned:planned.append(candidate)
                self._phase(operation_id,'RESERVED',details)
                self._barrier('retention_intent',time.monotonic()+60)
            self.delete(candidate)
            if operation_id is not None:self._barrier('retention_done',time.monotonic()+60)
            rows=[r for r in rows if r[0]!=candidate]

    def recover(self):
        """Only after kernel lifetime-lock acquisition; never trusts presence alone."""
        deadline=time.monotonic()+30
        for bid, in self.db.execute("select id from backups where state='DELETING'").fetchall():
            p=self._directory('backups',bid)
            if p.exists():shutil.rmtree(p)
            # Absence is not proof that the parent directory entry was synced.
            sync_dir(p.parent)
            with self.tx():self.db.execute("update backups set state='DELETED' where id=?",(bid,))
        for ident,bid,state in self.db.execute("select id,backup_id,state from restores where state not in ('READY','RELEASED')").fetchall():
            p=self._directory('restores',ident)
            if p.exists():shutil.rmtree(p);sync_dir(p.parent)
            with self.tx():
                self.db.execute("update restores set state='RELEASED' where id=?",(ident,))
                self.db.execute('update backups set pins=pins-1 where id=? and pins>0',(bid,))
        for ident,kind,state,details in self.db.execute("select id,kind,state,details from ops where state not in ('AVAILABLE','READY','FAILED','CANCELLED','INTERRUPTED')").fetchall():
            d=json.loads(details)
            if state=='QUEUED':
                with self.tx():self.db.execute("update ops set state='INTERRUPTED',details=? where id=?",(json.dumps(dict(reason='Queued request interrupted by restart',reserved=0)),ident))
                continue
            if kind=='backup':
                stage=self._directory('staging',ident);final=self._directory('backups',ident)
                if state=='PUBLISHING':
                    m=d['manifest'];p=final if final.exists() else stage
                    if json.loads((p/'manifest.json').read_text())!=m or verify_closed(p,m['expected'],self.cfg['artifact_bytes'],deadline)['sha256']!=m['sha256']:
                        raise Degraded('Uncertain publication retained for diagnosis')
                    if p==stage:stage.rename(final);sync_dir(final.parent);sync_dir(stage.parent)
                    with self.tx():
                        self.db.execute('insert or ignore into backups values(?,?,?,0)',(ident,json.dumps(m),'AVAILABLE'))
                        self.db.execute("update ops set state='AVAILABLE',details=? where id=?",(json.dumps(dict(manifest=m,reserved=0,recovered=True,retention_deleted=d.get('retention_deleted',[]),retention_planned=d.get('retention_planned',[]))),ident))
                else:
                    if final.exists():raise Degraded('Unexplained published object')
                    if stage.exists():shutil.rmtree(stage);sync_dir(stage.parent)
                    with self.tx():self.db.execute("update ops set state='FAILED',details=? where id=?",(json.dumps(dict(reason='Interrupted before publication',reserved=0,retention_deleted=d.get('retention_deleted',[]),retention_planned=d.get('retention_planned',[]))),ident))
            else:
                with self.tx():self.db.execute("update ops set state='FAILED',details=? where id=?",(json.dumps(dict(reason='Interrupted restore',reserved=0)),ident))
        # Missing catalog entries/unknown directories never become deletion candidates.
        for area,table in (('backups','backups'),('restores','restores')):
            known={r[0] for r in self.db.execute('select id from '+table)}
            if any(p.name not in known for p in (self.root/area).iterdir()):raise Degraded('Unknown inventory retained')
        if any((self.root/'staging').iterdir()):raise Degraded('Unknown staging retained')
        for bid, in self.db.execute("select id from backups where state='AVAILABLE'"):
            self._validated(bid,deadline)
        for rid,bid,m in self.db.execute("select id,backup_id,manifest from restores where state='READY'"):
            m=json.loads(m);p=self._directory('restores',rid)
            if verify_closed(p,m['expected'],self.cfg['artifact_bytes'],deadline)['sha256']!=m['sha256']:
                raise Degraded('Restored instance mismatch')
        for bid,pins in self.db.execute('select id,pins from backups'):
            actual=self.db.execute("select count(*) from restores where backup_id=? and state!='RELEASED'",(bid,)).fetchone()[0]
            if pins!=actual:raise Degraded('Pin inventory disagreement')


def diagnose(root):
    """Read-only observations, never a claim of reconciled readiness."""
    root=Path(root).resolve();value=dict(mode='READ_ONLY_DIAGNOSTIC',usage=usage(root))
    try:
        with contextlib.closing(readonly(root/'catalog.sqlite')) as c:
            value['authority']=c.execute('select epoch,revision from authority').fetchall()
            value['backups']=c.execute('select id,state,pins from backups').fetchall()
    except Exception as exc:value['catalog_error']=type(exc).__name__
    return value
