"""Reproducible phase-one scenarios against real installed service/worker processes."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import uuid
from keepweft.core import Controller
from keepweft.data import Refused,init_ledger,runtime
from keepweft.service import call
from .evidence import require

TERMINAL=('AVAILABLE','FAILED','CANCELLED','INTERRUPTED')
OWNED=[]

def wait(fn, timeout=10):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        v=fn()
        if v:return v
        time.sleep(.01)
    raise TimeoutError('Scenario observation timed out')

class Harness:
    def __init__(self,path,cap=4,queue=2):
        self.p=Path(path).resolve();self.p.mkdir(parents=True);self.root=self.p/'store'
        self.source=self.p/'source.sqlite';self.uid=init_ledger(self.source,40)
        self.barrier=self.p/'barriers';self.barrier.mkdir()
        self.options=self.p/'options.json';self.options.write_text(json.dumps(dict(max_receipts=cap)))
        self.queue=queue;self.proc=None;self.log=None;self.children=[]
    def start(self):
        self.log=open(self.p/'service.log','a')
        self.proc=subprocess.Popen([sys.executable,'-m','keepweft.service','--root',str(self.root),'--source',str(self.source),'--uuid',self.uid,'--options',str(self.options),'--queue-limit',str(self.queue),'--barriers',str(self.barrier)],stdout=self.log,stderr=self.log,start_new_session=True)
        self.children.append(self.proc);OWNED.append(self.proc)
        def ready():
            if self.proc.poll() is not None:raise RuntimeError('Service exited: '+(self.p/'service.log').read_text()[-2000:])
            try:return self.ok('status',{})
            except (OSError,ConnectionError):return None
        return wait(ready)
    def stop(self,kill=False):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.kill() if kill else self.proc.terminate()
                try:self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill();self.proc.wait(timeout=5)
                    raise  # cleanup succeeded, but timeout must remain a failure
        finally:
            if self.log:self.log.close();self.log=None
    def close(self):
        try:self.stop()
        finally:
            for p in self.children:
                if p.poll() is None:p.kill();p.wait(timeout=5)
    def ok(self,action,args):
        reply=call(self.root,action,args)
        require(reply['ok'] is True,'Unexpected reply '+str(reply));return reply['result']
    def envelope(self,timeout=10):return dict(**self.ok('status',{})['namespace'],request_id=uuid.uuid4().hex,command=dict(kind='backup',timeout=timeout))
    def lookup(self,e):return self.ok('lookup',{k:e[k] for k in ('epoch','generation','request_id')})
    def terminal(self,e):return wait(lambda:(r if (r:=self.lookup(e))['state'] in TERMINAL else None))
    def arm(self,name):
        for suffix in ('seen','release'):(self.barrier/(name+'.'+suffix)).unlink(missing_ok=True)
        (self.barrier/(name+'.arm')).touch()
    def seen(self,name):return wait(lambda:(self.barrier/(name+'.seen')).exists())
    def release(self,name):
        (self.barrier/(name+'.release')).touch();(self.barrier/(name+'.arm')).unlink(missing_ok=True)
    def files(self):return sorted(p.name for p in (self.root/'backups').iterdir())

@contextlib.contextmanager
def harness(root,**kw):
    h=Harness(root,**kw)
    try:h.start();yield h
    finally:h.close()


def dedup(root):
    with harness(root) as h:
        e=h.envelope();first=h.ok('submit',e);done=h.terminal(e)
        repeated=h.ok('submit',e)
        require(first['operation_id']==done['operation_id']==repeated['operation_id'] and done['state']=='AVAILABLE','Duplicate result mismatch')
        bad=dict(e,command=dict(kind='backup',timeout=11));conflict=call(h.root,'submit',bad)
        require(conflict['code']=='CONFLICT' and len(h.files())==1,'Conflict mutated inventory')
        h.stop();h.start();old=h.ok('submit',e)
        stale=dict(e,request_id=uuid.uuid4().hex);rejected=call(h.root,'submit',stale)
        require(old['operation_id']==first['operation_id'] and rejected['code']=='RETIRED' and len(h.files())==1,'Restart replay')
        return dict(state=done['state'],same_operation=True,objects=1,conflict=conflict['code'],old_epoch_new_key=rejected['code'],restart_replay_readonly=True)


def capacity(root):
    p=Path(root);p.mkdir();source=p/'source.sqlite';uid=init_ledger(source,12);store=p/'store'
    with Controller(store,source,uid,dict(max_receipts=2)) as c:
        a=c.backup();b=c.backup();before=[(r['id'],r['state']) for r in c.status()['backups']]
        hashes={x:hashlib.sha256((store/'backups'/x/'db.sqlite').read_bytes()).hexdigest() for x in (a['id'],b['id'])}
        try:c.backup()
        except Refused:pass
        else:raise ValueError('Receipt exhaustion accepted')
        after=[(r['id'],r['state']) for r in c.status()['backups']]
        require(before==after and all(hashlib.sha256((store/'backups'/x/'db.sqlite').read_bytes()).hexdigest()==v for x,v in hashes.items()),'Refusal deleted old backup')
    return dict(receipt_limit=2,available_preserved=2,hashes_preserved=True,refusal_before_prune=True)


def saturated_cancel(root):
    with harness(root,cap=2,queue=1) as h:
        h.arm('snapshot_open');a=h.envelope();h.ok('submit',a);h.seen('snapshot_open')
        b=h.envelope();h.ok('submit',b)
        extra=call(h.root,'submit',h.envelope())
        rotation=call(h.root,'rotate',h.ok('status',{})['namespace'])
        require(extra['code']=='RECEIPT_FULL' and rotation['code']=='BUSY','Limits bypassed')
        t=time.monotonic();status=h.ok('status',{});status_seconds=time.monotonic()-t
        cb=h.ok('cancel',b);ca=h.ok('cancel',a)
        require(cb['outcome']=='CANCELLED' and ca['outcome']=='CANCEL_ACCEPTED','Cancel requires capacity')
        result=h.terminal(a)
        require(result['state']=='CANCELLED' and h.terminal(b)['state']=='CANCELLED' and not h.files() and not list((h.root/'staging').iterdir()),'Cancel leaked/published')
        return dict(queue_limit=1,receipt_limit=2,full_code=extra['code'],rotation=rotation['code'],status_seconds=status_seconds,queued_cancel=cb['outcome'],active_cancel=ca['outcome'],terminal='CANCELLED',objects=0,staging_empty=True)


def boundary(root, point, cancel_wins):
    with harness(root) as h:
        h.arm(point);e=h.envelope();h.ok('submit',e);h.seen(point)
        cancel=h.ok('cancel',e)
        if cancel_wins:
            h.release(point);r=h.terminal(e)
            require(cancel['outcome']=='CANCEL_ACCEPTED' and r['state']=='CANCELLED' and not h.files(),'Cancellation lost before intent')
        else:
            require(cancel['outcome']=='TOO_LATE','Cancellation accepted after intent')
            h.stop(kill=True);h.release(point);h.start();r=h.lookup(e)
            require(r['state']=='AVAILABLE' and len(h.files())==1,'Intent did not recover')
        return dict(point=point,cancel=cancel['outcome'],state=r['state'],objects=len(h.files()),restart_after_intent=not cancel_wins)


def generation(root):
    with harness(root,cap=1) as h:
        originals=[];counts=[]
        for i in range(3):
            e=h.envelope();h.ok('submit',e);require(h.terminal(e)['state']=='AVAILABLE','Backup failed');originals.append(e)
            ns=h.ok('status',{})['namespace'];h.ok('rotate',ns);counts.append(h.ok('status',{})['receipts'])
        before=h.files();gone=call(h.root,'submit',originals[0]);lookup=call(h.root,'lookup',{k:originals[0][k] for k in ('epoch','generation','request_id')})
        require(gone['code']=='RETIRED' and lookup['code']=='RESULT_GONE' and h.files()==before and max(counts)<=1,'GC replay or growth')
        # Crash after namespace advance but before historical GC.
        h.arm('generation_advanced');ns=h.ok('status',{})['namespace']
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
            s.connect(str(h.root/'control.sock'));s.sendall((json.dumps(dict(action='rotate',args=ns))+'\n').encode());h.seen('generation_advanced');h.stop(kill=True)
        h.release('generation_advanced');new=h.start()['namespace']
        stale=call(h.root,'submit',originals[-1]);require(stale['code']=='RETIRED','Post-crash replay')
        require(new['generation']==ns['generation']+1 and h.files()==before,'Generation did not persist')
        return dict(completed_rollovers=4,retained_receipts_after_each=counts,forgotten_submit=gone['code'],forgotten_lookup=lookup['code'],crash_after_advance=True,old_key_after_crash=stale['code'],no_new_objects=True)


def lost_response(root,point):
    with harness(root) as h:
        h.arm(point);e=h.envelope()
        # Send without reading a response; receipt is the witness, not client success.
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
            s.connect(str(h.root/'control.sock'));s.sendall((json.dumps(dict(action='submit',args=e))+'\n').encode())
            h.seen(point)
        first=h.lookup(e);h.stop(kill=True);h.release(point);h.start()
        after=h.ok('submit',e)
        expect='FAILED' if point=='admitted' else 'AVAILABLE'
        require(first['operation_id']==after['operation_id'] and after['state']==expect,'Lost response replayed')
        require(len(h.files())==(0 if point=='admitted' else 1),'Lost response duplicate')
        return dict(point=point,response_not_read=True,same_operation=True,state=after['state'],objects=len(h.files()))


def cancelled_crash(root):
    with harness(root) as h:
        h.arm('before_publish');e=h.envelope();h.ok('submit',e);h.seen('before_publish')
        require(h.ok('cancel',e)['outcome']=='CANCEL_ACCEPTED','Cancel failed')
        h.stop(kill=True);h.release('before_publish');h.start();r=h.lookup(e)
        require(r['state']=='CANCELLED' and not h.files(),'Durable cancel published on recovery')
        return dict(cancel_durable_before_kill=True,state=r['state'],objects=0)


def deadline(root):
    with harness(root) as h:
        h.arm('before_publish');e=h.envelope(timeout=.5);h.ok('submit',e);r=h.terminal(e)
        require(r['state']=='FAILED' and not h.files() and not list((h.root/'staging').iterdir()),'Timeout faked success')
        return dict(state=r['state'],objects=0,staging_empty=True)

def retention_crash(root):
    with harness(root) as h:
        a=h.envelope();h.ok('submit',a);aid=h.terminal(a)['operation_id']
        b=h.envelope();h.ok('submit',b);bid=h.terminal(b)['operation_id']
        h.arm('retention_done');e=h.envelope();h.ok('submit',e);h.seen('retention_done')
        h.stop(kill=True);h.release('retention_done');h.start();r=h.lookup(e)
        require(r['state']=='FAILED' and r['retention_deleted']==[aid] and h.files()==[bid],'Retention attribution lost across crash')
        return dict(state='FAILED',deleted_attributed=True,latest_preserved=True,objects=1)

CASES=(('dedup_restart',dedup),('receipt_refusal',capacity),('saturated_cancel',saturated_cancel),
       ('cancel_before_intent',lambda r:boundary(r,'before_publish',True)),
       ('cancel_after_intent',lambda r:boundary(r,'publish_intent',False)),('generation_gc',generation),
       ('lost_admission',lambda r:lost_response(r,'admitted')),('lost_rename',lambda r:lost_response(r,'after_rename')),
       ('lost_catalog',lambda r:lost_response(r,'after_catalog')),('cancel_crash',cancelled_crash),('deadline',deadline),('retention_crash',retention_crash))

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--source-sha',required=True);a=p.parse_args()
    require(sys.platform=='linux' and Path('/proc').is_dir(),'Guest fault runner requires Linux /proc observations')
    a.root.mkdir(parents=True);out=a.root/'evidence.json'
    v=dict(passed=False,source_sha256=a.source_sha,runtime=runtime(),cases=[],limits=dict(vm_reboot_tested=False,power_loss_tested=False,managed_reader_tested=False,scheduler_tested=False))
    try:
        for name,fn in CASES:
            row=dict(name=name,passed=False);v['cases'].append(row);start=time.monotonic()
            try:row['details']=fn(a.root/name);row['passed']=True
            finally:row['seconds']=time.monotonic()-start;out.write_text(json.dumps(v,indent=2)+'\n')
        require(all(p.poll() is not None for p in OWNED),'Owned service process still running')
        remaining=[]
        for p in Path('/proc').glob('[0-9]*/cmdline'):
            try:parts=p.read_bytes().split(b'\0')
            except (FileNotFoundError,PermissionError,ProcessLookupError):continue
            if b'keepweft.service' in parts or b'keepweft.worker' in parts:remaining.append(int(p.parent.name))
        require(not remaining,'Service/worker processes remain in isolated VM')
        v.update(owned_services_exited=True,owned_service_count=len(OWNED),no_service_or_worker_processes_remaining=True)
        v['passed']=True
    except BaseException as exc:v['error']=type(exc).__name__+': '+str(exc);raise
    finally:out.write_text(json.dumps(v,indent=2)+'\n')
if __name__=='__main__':main()
