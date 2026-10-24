"""Real service/reader scenarios, shared by portable tests and installed-wheel VM runs."""
import argparse
import fcntl
import sqlite3
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from keepweft.data import runtime,digest_file
from keepweft.service import call
from .phase1_cases import Harness,wait
from .evidence import require

OWNED_READERS=[]

class Readers(Harness):
    def __init__(self,path):super().__init__(path,cap=16)
    def cmd(self,command,ident,token=None):
        if token is None:token=self.ok('status',{})['inventory']['token']
        reply=call(self.root,'reader',dict(command=command,id=ident,token=token),timeout=15)
        require(reply['ok'],'Reader command failed: '+str(reply));return reply['result']
    def reject(self,command,ident,token=None):
        if token is None:token=self.ok('status',{})['inventory']['token']
        reply=call(self.root,'reader',dict(command=command,id=ident,token=token),timeout=15)
        require(reply['ok'] is False,'Unsafe operation accepted');return reply
    def inventory(self):return self.ok('status',{})['inventory']
    def setup_copy(self):
        e=self.envelope();self.ok('submit',e);b=self.terminal(e)
        require(b['state']=='AVAILABLE','Backup failed')
        r=self.cmd('restore',b['result_id']);return b['result_id'],r['id']
    def own(self,rid):
        # Test cleanup owns the PID observed from this exact launched reader.
        # Production controller never signals this persisted PID after recovery.
        info=json.loads((self.root/'guards'/(rid+'.ready')).read_text());pid=info['pid'];OWNED_READERS.append(pid);return pid
    def pin(self,bid):return next(b['pins'] for b in self.inventory()['backups'] if b['id']==bid)
    def close(self):
        for pid,rid in getattr(self,'test_pids',[]):
            # Only kill our observed reader while its original lifetime guard is busy.
            fd=os.open(self.root/'guards'/rid,os.O_RDWR)
            try:
                try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:
                    try:os.kill(pid,signal.SIGCONT);os.kill(pid,signal.SIGKILL)
                    except ProcessLookupError:pass
            finally:os.close(fd)
        super().close()
    def track(self,rid):
        pid=self.own(rid)
        if not hasattr(self,'test_pids'):self.test_pids=[]
        self.test_pids.append((pid,rid));return pid


def rss(pid):
    if Path('/proc/'+str(pid)+'/status').exists():
        return int(next(line.split()[1] for line in Path('/proc/'+str(pid)+'/status').read_text().splitlines() if line.startswith('VmRSS:')))
    return int(subprocess.check_output(['ps','-o','rss=','-p',str(pid)],text=True,timeout=3).strip())


def roundtrip(path):
    h=Readers(path)
    try:
        h.start();bid,rid=h.setup_copy();original=digest_file(h.root/'backups'/bid/'db.sqlite')
        old_token=h.inventory()['token']
        t=time.monotonic();started=h.cmd('start',rid);elapsed=time.monotonic()-t;pid=h.track(rid)
        query=h.cmd('query',rid);reader_rss=rss(pid);service_rss=rss(h.proc.pid);logical=h.inventory()['usage']['logical_bytes']
        require(query==started['summary'] and query['uuid']==h.uid and query['count']==40 and query['max_seq']==40,'Wrong snapshot')
        h.reject('release',rid);require(h.pin(bid)==1,'Live reader unpinned')
        stopped=h.cmd('stop',rid);require(stopped['exit_proven'] is True,'Stop not proven')
        rejected=h.reject('release',rid,old_token)
        require(rejected['detail']=='Explicit current epoch/revision required','Stale revision masked by busy guard')
        missing=call(h.root,'reader',dict(command='release',id=rid,token=None))
        require(missing['ok'] is False and missing['detail']=='Explicit current epoch/revision required' and h.pin(bid)==1,'Missing token bypassed fence')
        result=h.cmd('release',rid);require(result['state']=='RELEASED' and h.pin(bid)==0 and not (h.root/'restores'/rid).exists(),'Release incomplete')
        require(digest_file(h.root/'backups'/bid/'db.sqlite')==original,'Backup modified')
        return dict(count=40,hash_preserved=True,pin_while_serving=1,pin_after_release=0,release_refused_while_serving=True,stale_revision_rejected_with_free_guard=True,missing_token_rejected=True,start_to_query_seconds=elapsed,reader_rss_kib=reader_rss,controller_rss_kib=service_rss,managed_logical_bytes_while_serving=logical)
    finally:h.close()


def orphan(path):
    h=Readers(path)
    try:
        h.start();bid,rid=h.setup_copy();h.cmd('start',rid);pid=h.track(rid);stale=h.inventory()['token'];h.stop(kill=True);h.start()
        inv=h.inventory();require(inv['restores'][0]['state']=='ORPHAN_BUSY' and h.pin(bid)==1,'Lost live occupancy')
        require(h.cmd('query',rid)['count']==40,'Reader died with controller/global lock')
        h.reject('start',rid);h.reject('restore',bid);h.reject('release',rid);rejected=h.reject('release',rid,stale)
        require(rejected['detail']=='Explicit current epoch/revision required','Stale epoch masked by guard refusal')
        outcome=h.cmd('stop',rid);require(outcome['state']=='ORPHAN_BUSY' and outcome['exit_proven'] is False,'Unknown process signalled')
        os.kill(pid,signal.SIGSTOP);h.reject('release',rid);require(h.pin(bid)==1 and (h.root/'restores'/rid/'db.sqlite').exists(),'Paused reader erased')
        os.kill(pid,signal.SIGCONT);os.kill(pid,signal.SIGKILL)
        def free():
            r=h.cmd('stop',rid);return r if r['exit_proven'] else None
        wait(free);h.cmd('release',rid);require(h.pin(bid)==0,'Dead reader pin leaked')
        return dict(controller_sigkill=True,global_controller_recovered=True,orphan_state='ORPHAN_BUSY',reader_query_after_restart=40,paused_reader_retained=True,stale_release_rejected=True,unknown_pid_not_signalled=True,pin_after_proven_exit=0)
    finally:h.close()


def spawn_crash(path,point):
    h=Readers(path)
    try:
        h.start();bid,rid=h.setup_copy();h.arm(point)
        token=h.inventory()['token']
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
            s.connect(str(h.root/'control.sock'));s.sendall((json.dumps(dict(action='reader',args=dict(command='start',id=rid,token=token)))+'\n').encode());h.seen(point)
            if point=='reader_after_spawn':
                wait(lambda:(h.root/'guards'/(rid+'.ready')).exists());pid=h.track(rid)
            h.stop(kill=True)
        h.release(point);h.start();state=h.inventory()['restores'][0]['state']
        expected='ORPHAN_BUSY' if point=='reader_after_spawn' else 'READY'
        require(state==expected and h.pin(bid)==1,'Spawn handoff lost occupancy')
        if point=='reader_after_spawn':
            h.reject('release',rid);os.kill(pid,signal.SIGKILL);wait(lambda:h.cmd('stop',rid)['exit_proven'])
        h.cmd('release',rid)
        return dict(barrier_seen=point,state_after_restart=state,pin_after_restart=1,pin_after_release=h.pin(bid))
    finally:h.close()


def release_crash(path):
    h=Readers(path)
    try:
        h.start();bid,rid=h.setup_copy();h.arm('reader_release_intent');token=h.inventory()['token']
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
            s.connect(str(h.root/'control.sock'));s.sendall((json.dumps(dict(action='reader',args=dict(command='release',id=rid,token=token)))+'\n').encode());h.seen('reader_release_intent');h.stop(kill=True)
        require((h.root/'restores'/rid/'db.sqlite').exists(),'Not an intent crash')
        h.release('reader_release_intent');h.start();require(h.pin(bid)==0 and h.inventory()['restores'][0]['state']=='RELEASED' and not (h.root/'restores'/rid).exists(),'Release recovery failed')
        return dict(barrier_seen='reader_release_intent',copy_present_before_restart=True,state_after_restart='RELEASED',pin_after_restart=0)
    finally:h.close()


def stopped_reader(path):
    h=Readers(path)
    try:
        h.start();bid,rid=h.setup_copy();h.cmd('start',rid);pid=h.track(rid);os.kill(pid,signal.SIGSTOP)
        stopped=h.cmd('stop',rid);require(stopped['state']=='STOP_REQUESTED' and stopped['exit_proven'] is False,'Stop timeout counted as exit')
        h.reject('release',rid);require(h.pin(bid)==1,'Timed out stop unpinned')
        os.kill(pid,signal.SIGCONT);wait(lambda:h.cmd('stop',rid)['exit_proven']);h.cmd('release',rid)
        return dict(stop_timeout_not_exit=True,pin_after_timeout=1,release_refused=True,pin_after_exit=0)
    finally:h.close()

def missing_ready(path,crash):
    h=Readers(path)
    try:
        h.start();bid,rid=h.setup_copy();h.arm('reader_before_ready');token=h.inventory()['token']
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
            sock.settimeout(10);sock.connect(str(h.root/'control.sock'));sock.sendall((json.dumps(dict(action='reader',args=dict(command='start',id=rid,token=token)))+'\n').encode())
            h.seen('reader_before_ready');pid=int((h.barrier/'reader_before_ready.seen').read_text());h.test_pids=[(pid,rid)]
            require(not (h.root/'guards'/(rid+'.ready')).exists(),'Handshake already present')
            if crash:
                h.stop(kill=True);h.start();require(h.inventory()['restores'][0]['state']=='ORPHAN_BUSY','Missing readiness freed reader')
                h.reject('release',rid);require(h.pin(bid)==1,'Missing readiness unpinned')
                os.kill(pid,signal.SIGKILL)
            else:
                raw=b''
                while b'\n' not in raw:
                    chunk=sock.recv(4096)
                    require(bool(chunk),'Timeout reply dropped');raw+=chunk
                reply=json.loads(raw);require(reply['ok'] is False and reply['code']=='TimeoutError','Missing handshake accepted or unrelated failure')
                require(h.pin(bid)==1 and h.inventory()['restores'][0]['state']=='STOP_REQUESTED','Deadline unpinned')
        wait(lambda:h.cmd('stop',rid)['exit_proven']);h.cmd('release',rid)
        return dict(barrier_seen='reader_before_ready',ready_absent=True,controller_crashed=crash,pin_before_exit=1,pin_after_release=0,deadline_error=None if crash else 'TimeoutError')
    finally:h.close()

def readonly_release(path):
    h=Readers(path);mounted=False
    try:
        h.start();bid,rid=h.setup_copy();target=h.root/'restores'/rid
        subprocess.run(['mount','--bind',str(target),str(target)],check=True,timeout=10);mounted=True
        subprocess.run(['mount','-o','remount,bind,ro',str(target)],check=True,timeout=10)
        error=h.reject('release',rid)
        require(error['code']=='OSError' and '[Errno 30]' in error['detail'],'Not actual EROFS')
        require(h.pin(bid)==1 and target.exists() and h.inventory()['blocked'] is True,'IO refusal freed reference')
        h.stop();refused=False
        try:h.start()
        except RuntimeError:refused=True
        require(refused,'Restart ignored failed deletion')
        subprocess.run(['umount',str(target)],check=True,timeout=10);mounted=False
        h.start();require(h.pin(bid)==0 and not target.exists(),'Repair did not finish release')
        return dict(os_errno=30,pin_before_repair=1,restart_refused=True,pin_after_repair=0,readonly_mount_removed=True)
    finally:
        if mounted:subprocess.run(['umount',str(target)],check=True,timeout=10)
        h.close()

CASES=(('roundtrip',roundtrip),('controller_orphan',orphan),('before_spawn',lambda p:spawn_crash(p,'reader_before_spawn')),('after_spawn',lambda p:spawn_crash(p,'reader_after_spawn')),('release_intent',release_crash),('stop_timeout',stopped_reader),('missing_ready_crash',lambda p:missing_ready(p,True)),('readiness_timeout',lambda p:missing_ready(p,False)))

VM_CASES=CASES+(('readonly_release',readonly_release),)

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--source-sha',required=True);a=p.parse_args();a.root.mkdir(parents=True)
    v=dict(passed=False,source_sha256=a.source_sha,runtime=runtime(),cases=[],limits=dict(vm_reboot_tested=False,power_loss_tested=False,reader_adoption_tested=False,long_term_gc_tested=False))
    try:
        for name,fn in VM_CASES:
            t=time.monotonic()
            try:details=fn(a.root/name);v['cases'].append(dict(name=name,passed=True,seconds=time.monotonic()-t,details=details))
            except BaseException as exc:
                v['cases'].append(dict(name=name,passed=False,seconds=time.monotonic()-t,error=type(exc).__name__+': '+str(exc)));raise
        from .phase1_cases import OWNED
        v['owned_service_count']=len(OWNED);v['owned_services_exited']=all(p.poll() is not None for p in OWNED)
        # Actual Linux process scan; zombie-only entries have exited and hold no FDs.
        remaining=[]
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit():continue
            try:
                cmd=(proc/'cmdline').read_bytes()
                if any(b'-m\0'+x in cmd for x in (b'keepweft.service',b'keepweft.worker',b'keepweft.view')):remaining.append(proc.name)
            except (OSError,ProcessLookupError):pass
        v['no_service_or_worker_processes_remaining']=not remaining
        require(v['owned_services_exited'] and not remaining,'Process cleanup incomplete');v['passed']=True
    finally:(a.root/'evidence.json').write_text(json.dumps(v,indent=2)+'\n')
if __name__=='__main__':main()
