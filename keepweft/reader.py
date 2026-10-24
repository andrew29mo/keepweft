"""Single managed reader. Kernel guard ownership, never PID/timeout, proves release safety."""
import contextlib
import fcntl
import json
import math
import os
import secrets
import shutil
import subprocess
import sys
import time
from urllib.request import Request,build_opener,ProxyHandler
from .data import Refused, sync_dir, verify_closed


def guard_path(c, ident):
    c._directory('restores',ident)  # identity validation before path construction
    return c.root/'guards'/ident


def create_guard(c, ident):
    fd=os.open(guard_path(c,ident),os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o600)
    os.close(fd);sync_dir(c.root/'guards')


@contextlib.contextmanager
def guard(c, ident):
    # Separate open file description, not a duplicate of an inherited lock.
    fd=os.open(guard_path(c,ident),os.O_RDWR|os.O_NOFOLLOW)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise Refused('Reader occupancy unknown/busy; copy and pin retained') from exc
        yield fd
    finally:os.close(fd)  # no LOCK_UN: a spawned reader may still hold the OFD


def state(c, ident):
    row=c.db.execute('select state,manifest from restores where id=?',(ident,)).fetchone()
    if row is None or row[0]=='RELEASED':raise Refused('Restore unavailable')
    return row[0],json.loads(row[1])


def transition(c, ident, value, info=None):
    with c.tx():
        c.db.execute('update restores set state=? where id=?',(value,ident))
        if info is not None:c.db.execute('insert or replace into readers values(?,?)',(ident,json.dumps(info)))
        c._revision()


def limit(timeout):
    if type(timeout) not in (float,int) or not math.isfinite(timeout) or not 0<timeout<=10:
        raise Refused('Reader timeout must be in (0,10]')
    return time.monotonic()+timeout


def query(c, ident, timeout=2):
    _,m=state(c,ident)
    row=c.db.execute('select info from readers where id=?',(ident,)).fetchone()
    if row is None:raise Refused('No reader endpoint')
    info=json.loads(row[0])
    request=Request('http://127.0.0.1:'+str(info['port'])+'/summary',headers={'Authorization':'Bearer '+info['nonce']})
    with build_opener(ProxyHandler({})).open(request,timeout=timeout) as response:
        raw=response.read(4097)
    if len(raw)>4096:raise Refused('Oversized reader response')
    result=json.loads(raw)
    expected=dict(uuid=m['expected']['uuid'],count=m['expected']['count'],max_seq=m['expected']['max_seq'],instance_id=ident,nonce=info['nonce'])
    if result!=expected:raise Refused('Reader identity/content mismatch')
    return result


def start(c, ident, token, timeout=3):
    c._check(token);deadline=limit(timeout);current,m=state(c,ident)
    if current!='READY':raise Refused('Reader must be stopped with proven free guard')
    with guard(c,ident) as fd:
        target=c._directory('restores',ident)
        if verify_closed(target,m['expected'],c.cfg['artifact_bytes'],deadline)['sha256']!=m['sha256']:
            raise Refused('Restore content mismatch')
        nonce=secrets.token_hex(16);ready=c.root/'guards'/(ident+'.ready');ready.unlink(missing_ok=True)
        transition(c,ident,'STARTING',dict(nonce=nonce))
        c._barrier('reader_before_spawn',deadline)
        proc=subprocess.Popen([sys.executable,'-m','keepweft.view','--database',str(target/'db.sqlite'),'--ready',str(ready),'--guard-fd',str(fd),'--instance-id',ident,'--nonce',nonce,*(['--barriers',str(c.barriers)] if c.barriers else [])],pass_fds=(fd,),start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        c.readers[ident]=proc
        try:
            c._barrier('reader_after_spawn',deadline)
            while time.monotonic()<deadline:
                if proc.poll() is not None:raise Refused('Reader exited before readiness')
                if ready.exists():
                    info=json.loads(ready.read_text())
                    if info.get('nonce')!=nonce:raise Refused('Stale readiness')
                    transition(c,ident,'STARTING',info)
                    observed=query(c,ident,timeout=max(.01,min(.25,deadline-time.monotonic())))
                    transition(c,ident,'SERVING')
                    return dict(id=ident,state='SERVING',summary=observed)
                time.sleep(.01)
            raise TimeoutError('Reader readiness deadline')
        except BaseException:
            # Only signal our own unreaped child, never a persisted PID.
            if proc.poll() is None:proc.kill()
            try:proc.wait(timeout=2)
            except subprocess.TimeoutExpired:pass
            # Separate-FD reconciliation occurs after this inherited FD closes.
            transition(c,ident,'STOP_REQUESTED')
            raise


def stop(c, ident, token, timeout=2):
    c._check(token);deadline=limit(timeout);current,_=state(c,ident)
    proc=c.readers.get(ident)
    if proc is not None:
        transition(c,ident,'STOP_REQUESTED')
        if proc.poll() is None:proc.terminate()
        try:proc.wait(timeout=max(.01,deadline-time.monotonic()))
        except subprocess.TimeoutExpired:
            # Timeout is not death. Keep copy and pin; caller can retry.
            return dict(id=ident,state='STOP_REQUESTED',exit_proven=False)
    try:
        with guard(c,ident):transition(c,ident,'READY',{})
    except Refused:
        transition(c,ident,'ORPHAN_BUSY')
        return dict(id=ident,state='ORPHAN_BUSY',exit_proven=False)
    return dict(id=ident,state='READY',exit_proven=True)


def finish_release(c, ident, bid):
    p=c._directory('restores',ident)
    if p.exists():shutil.rmtree(p)
    # Required even after an earlier interrupted unlink removed the directory.
    sync_dir(p.parent)
    with c.tx():
        c.db.execute("update restores set state='RELEASED' where id=?",(ident,))
        c.db.execute('update backups set pins=pins-1 where id=? and pins>0',(bid,))
        c.db.execute('delete from readers where id=?',(ident,));c._revision()


def release(c, ident, token=None):
    c._check(token);current,_=state(c,ident)
    with guard(c,ident):
        bid=c.db.execute('select backup_id from restores where id=?',(ident,)).fetchone()[0]
        transition(c,ident,'RELEASING')
        try:
            c._barrier('reader_release_intent',time.monotonic()+10)
            finish_release(c,ident,bid)
        except BaseException:
            c.blocked=True
            raise
    proc=c.readers.pop(ident,None)
    if proc is not None:proc.poll()  # reap an exited owned child
    return dict(id=ident,state='RELEASED')


def recover(c):
    for ident,bid,current in c.db.execute("select id,backup_id,state from restores where state!='RELEASED'").fetchall():
        path=guard_path(c,ident)
        if not path.exists():
            if current!='MATERIALIZING':raise Refused('Legacy restore has no lifetime guard; manual offline reconciliation required')
            create_guard(c,ident)  # no spawn can precede guard creation
        try:
            with guard(c,ident):
                if current in ('MATERIALIZING','RELEASING'):
                    finish_release(c,ident,bid)
                else:transition(c,ident,'READY',{})
        except Refused:
            transition(c,ident,'ORPHAN_BUSY')
