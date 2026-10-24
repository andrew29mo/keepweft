"""Bounded installed-service closeout. No restarts inside resource trial."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from keepweft.data import digest_file, runtime
from keepweft.service import call
from .evidence import require
from .phase1_cases import wait
from .phase2_cases import Readers, rss

CYCLES=24
RSS_DRIFT_KIB=4096
READER_DWELL_SECONDS=5

class Closeout(Readers):
    def __init__(self,path,options=None):
        self.p=Path(path).resolve();self.p.mkdir(parents=True);self.root=self.p/'store'
        self.source=self.p/'source.sqlite'
        made=subprocess.run([sys.executable,'-m','keepweft.cli','init-source','--source',str(self.source),'--count','40'],capture_output=True,text=True,timeout=10)
        require(made.returncode==0,'Documented source initialization failed: '+made.stdout+made.stderr)
        self.uid=json.loads(made.stdout)['result']['uuid'];self.barrier=self.p/'barriers';self.barrier.mkdir()
        self.options=self.p/'options.json';self.options.write_text(json.dumps({'max_receipts':128,**(options or {})}))
        self.proc=None;self.log=None;self.children=[]
    def cli(self,*args,ok=True):
        p=subprocess.run([sys.executable,'-m','keepweft.client',*args,'--root',str(self.root)],capture_output=True,text=True,timeout=20)
        v=json.loads(p.stdout)
        require((p.returncode==0)==ok and v['ok']==ok,'CLI exit/result mismatch: '+p.stdout+p.stderr)
        return v
    def cli_reader(self,command,ident):
        token=self.p/'token.json';token.write_text(json.dumps(self.inventory()['token']))
        return self.cli('reader','--command',command,'--id',ident,*(['--token',str(token)] if command!='query' else []))['result']
    def start(self):
        # Standard documented production invocation: no test barriers.
        self.log=open(self.p/'service.log','a')
        self.proc=subprocess.Popen([sys.executable,'-m','keepweft.service','--root',str(self.root),'--source',str(self.source),'--uuid',self.uid,'--options',str(self.options)],stdout=self.log,stderr=self.log,start_new_session=True)
        self.children.append(self.proc)
        from .phase1_cases import OWNED
        OWNED.append(self.proc)
        def ready():
            if self.proc.poll() is not None:raise RuntimeError('Formal service exited')
            try:return self.ok('status',{})
            except (OSError,ConnectionError):return None
        return wait(ready)


def documented(path):
    h=Closeout(path)
    try:
        # Demonstrate the actual documented entrypoints rather than direct core calls.
        h.start();saved=h.p/'request.json'
        h.cli('prepare','--envelope',str(saved));h.cli('submit','--envelope',str(saved))
        e=json.loads(saved.read_text());r=h.terminal(e);require(r['state']=='AVAILABLE','Backup failed')
        bid=r['result_id'];rid=h.cli_reader('restore',bid)['id'];h.cli_reader('start',rid);h.track(rid)
        q=h.cli_reader('query',rid);require(q['count']==q['max_seq']==40 and q['uuid']==h.uid,'Wrong restored data')
        require(h.cli_reader('stop',rid)['exit_proven'],'CLI stop failed');h.cli_reader('release',rid)
        require(h.pin(bid)==0 and not (h.root/'restores'/rid).exists(),'CLI release incomplete')
        mode=(h.root/'control.sock').stat().st_mode&0o777
        require(mode==0o600,'Socket permissions')
        h.stop();require(not (h.root/'control.sock').exists(),'Socket not removed')
        return dict(installed_cli=True,barriers=False,query_count=40,pin_after_release=0,socket_mode='0600',socket_removed=True)
    finally:h.close()


def hashes(h):
    return {p.name:digest_file(p/'db.sqlite') for p in (h.root/'backups').iterdir()}

def capacity(path,kind):
    # Separate declared logical-byte vs receipt policies, no injected config mutation.
    opts=dict(artifact_bytes=262144,headroom_bytes=65536,keep=8)
    opts.update(dict(max_receipts=4) if kind=='receipts' else dict(budget_bytes=1300000))
    h=Closeout(path,opts)
    try:
        h.start();bid,rid=h.setup_copy();h.cmd('start',rid);h.track(rid)
        attempts=[]
        for _ in range(12):
            before=hashes(h);status=h.ok('status',{});e=h.envelope();reply=call(h.root,'submit',e)
            attempts.append(dict(ok=reply['ok'],code=reply.get('code')))
            if not reply['ok']:
                require(reply['code']==('RECEIPT_FULL' if kind=='receipts' else 'Refused'),'Wrong capacity failure: '+str(reply))
                if kind=='logical_bytes':require(reply['detail']=='Capacity unavailable; previous backups preserved','Wrong space refusal')
                require(hashes(h)==before and h.ok('status',{})['receipts']==status['receipts'],'Refusal changed backup inventory/receipts')
                break
            require(h.terminal(e)['state']=='AVAILABLE','Admitted operation unexpectedly failed')
        else:raise ValueError('Capacity was never reached')
        require(h.pin(bid)==1 and h.cmd('query',rid)['count']==40,'Capacity harmed active reader')
        require(h.cmd('stop',rid)['exit_proven'],'Full store prevented stop');h.cmd('release',rid)
        require(h.pin(bid)==0 and not (h.root/'restores'/rid).exists(),'Full store prevented release')
        return dict(kind=kind,options=opts,attempts=attempts,refusal_code=attempts[-1]['code'],inventory_preserved_on_refusal=True,receipts_preserved_on_refusal=True,query_at_full=40,pin_before_stop=1,stop_exit_proven=True,pin_after_release=0,logical_bytes_after_release=h.inventory()['usage']['logical_bytes'])
    finally:h.close()


def sample(h,cycle):
    with sqlite3.connect('file:'+str(h.root/'catalog.sqlite')+'?mode=ro',uri=True) as db:
        rows={t:db.execute('select count(*) from '+t).fetchone()[0] for t in ('ops','requests','backups','restores','readers')}
        active=db.execute("select count(*) from restores where state!='RELEASED'").fetchone()[0]
        pins=db.execute('select coalesce(sum(pins),0) from backups').fetchone()[0]
    pid=h.proc.pid;children=Path('/proc/'+str(pid)+'/task/'+str(pid)+'/children').read_text().split()
    st=h.ok('status',{})
    return dict(cycle=cycle,pid=pid,rss_kib=rss(pid),fds=len(list(Path('/proc/'+str(pid)+'/fd').iterdir())),children=len(children),rows=rows,active_restores=active,pins=pins,guards=len(list((h.root/'guards').glob('*'))),files=sum(p.is_file() for p in h.root.rglob('*')),catalog_bytes=(h.root/'catalog.sqlite').stat().st_size,log_bytes=(h.p/'service.log').stat().st_size,**{k:st['inventory']['usage'][k] for k in ('logical_bytes','allocated_bytes')})


def validate_samples(samples,cycles=CYCLES):
    require([s['cycle'] for s in samples]==list(range(cycles+1)),'Missing resource observation')
    require(len({s['pid'] for s in samples})==1,'Restart hid growth')
    base=samples[4];end=samples[-1]
    require(max(s['rss_kib'] for s in samples[4:])-base['rss_kib']<=RSS_DRIFT_KIB,'RSS growth exceeded predeclared allowance')
    require(all(s['fds']==samples[0]['fds'] and s['children']==s['active_restores']==s['pins']==s['rows']['readers']==0 for s in samples),'FD/child/pin/reader leak')
    require(all(s['rows']['ops']==2*s['cycle'] and s['rows']['requests']==s['rows']['backups']==s['rows']['restores']==s['cycle'] and s['guards']==2*s['cycle'] for s in samples),'Metadata growth does not match retained records')
    require(all(s['catalog_bytes']<=2048*4096 and s['logical_bytes']<=64*1024*1024 and s['log_bytes']==0 for s in samples),'Budget/log growth')
    require(end['rows']['ops']<128,'Trial ended at cap instead of declared cycles')
    return True


def sustained(path):
    h=Closeout(path);started=time.monotonic()
    try:
        h.start();samples=[sample(h,0)];latencies=[]
        for cycle in range(1,CYCLES+1):
            t=time.monotonic();bid,rid=h.setup_copy();h.cmd('start',rid)
            require(h.cmd('query',rid)['count']==40,'Repeated query mismatch')
            time.sleep(READER_DWELL_SECONDS)
            require(h.cmd('query',rid)['count']==40,'Held reader query mismatch')
            require(h.cmd('stop',rid)['exit_proven'],'Repeated stop failed');h.cmd('release',rid)
            latencies.append(time.monotonic()-t);samples.append(sample(h,cycle))
        validate_samples(samples)
        return dict(cycles=CYCLES,reader_dwell_seconds=READER_DWELL_SECONDS,ledger_rows=40,restarts=0,warmup_cycles=4,rss_drift_allowance_kib=RSS_DRIFT_KIB,samples=samples,cycle_seconds=latencies,seconds=time.monotonic()-started,retained_metadata_explained=True,long_term_qualification=False)
    finally:h.close()


def catalog_snapshot(root):
    # Read-only, no formal controller: must not advance epoch/reconcile before witness.
    p=root/'catalog.sqlite'
    with sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True) as db:
        rows=dict(restores=db.execute('select id,backup_id,state from restores order by id').fetchall(),pins=db.execute('select id,pins from backups order by id').fetchall(),authority=db.execute('select epoch,revision from authority').fetchall())
    return json.loads(json.dumps(dict(sha256=digest_file(p),rows=rows)))


def boot_id():return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def reboot_prepare(path,kind):
    # Use actual formal Readers harness only for the controlled release-intent cut.
    h=Readers(path) if kind=='release_intent' else Closeout(path)
    try:
        h.start();bid,rid=h.setup_copy();h.cmd('start',rid);pid=h.track(rid);token=h.inventory()['token']
        if kind=='release_intent':
            require(h.cmd('stop',rid)['exit_proven'],'Stop before intent failed');h.arm('reader_release_intent')
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
                s.connect(str(h.root/'control.sock'));s.sendall((json.dumps(dict(action='reader',args=dict(command='release',id=rid,token=h.inventory()['token'])))+'\n').encode());h.seen('reader_release_intent');h.stop(kill=True)
            h.release('reader_release_intent')
        else:h.stop(kill=True)
        before=catalog_snapshot(h.root);expected='RELEASING' if kind=='release_intent' else 'SERVING'
        require(before['rows']['restores'][0][2]==expected and before['rows']['pins'][0][1]==1 and (h.root/'restores'/rid/'db.sqlite').exists(),'Pre-reboot state already cleaned')
        value=dict(kind=kind,bid=bid,rid=rid,uid=h.uid,reader_pid=pid,old_token=token,before=before,boot_before=boot_id(),copy_sha256=digest_file(h.root/'restores'/rid/'db.sqlite'),controller_killed_before_reboot=True)
        (Path(path)/'witness.json').write_text(json.dumps(value,indent=2)+'\n')
        return value
    finally:
        # Deliberately leave the serving reader alive across normal VM shutdown.
        # Controller was SIGKILLed; no shutdown hook can reconcile its catalog.
        h.stop()


def reboot_finish(path):
    path=Path(path);w=json.loads((path/'witness.json').read_text());root=path/'store';observed=catalog_snapshot(root)
    require(boot_id()!=w['boot_before'],'Not a VM reboot')
    require(observed==w['before'],'Shutdown or boot cleaned state before recovery witness')
    require(digest_file(root/'restores'/w['rid']/'db.sqlite')==w['copy_sha256'],'Copy changed before recovery')
    # No source initialization or Harness constructor: reopen original registered store.
    h=object.__new__(Closeout);h.p=path;h.root=root;h.source=path/'source.sqlite';h.uid=w['uid'];h.options=path/'options.json';h.proc=None;h.log=None;h.children=[];h.test_pids=[]
    try:
        h.start();inv=h.inventory();r=next(x for x in inv['restores'] if x['id']==w['rid']);want='RELEASED' if w['kind']=='release_intent' else 'READY'
        require(r['state']==want,'Formal recovery state mismatch')
        rejected=h.reject('release',w['rid'],w['old_token']);require(rejected['detail']=='Explicit current epoch/revision required','Old epoch not rejected')
        if want=='READY':
            require(h.pin(w['bid'])==1,'Recovered live reference lost');h.cmd('start',w['rid']);h.track(w['rid']);require(h.cmd('query',w['rid'])['count']==40,'Reboot query wrong');require(h.cmd('stop',w['rid'])['exit_proven'],'Reboot stop failed');h.cmd('release',w['rid'])
        require(h.pin(w['bid'])==0 and not (root/'restores'/w['rid']).exists(),'Reboot release/pin failed')
        return dict(kind=w['kind'],boot_before=w['boot_before'],boot_after=boot_id(),journal_before=w['before'],journal_after_before_controller=observed,copy_hash_preserved_before_recovery=True,controller_killed_before_reboot=True,state_after_recovery=want,old_epoch_rejected=True,query_count=40 if want=='READY' else None,pin_after_release=0)
    finally:h.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['cases','prepare','finish']);p.add_argument('--root',type=Path,required=True);p.add_argument('--kind',choices=['serving','release_intent']);a=p.parse_args()
    if a.action=='prepare':value=reboot_prepare(a.root,a.kind)
    elif a.action=='finish':value=reboot_finish(a.root)
    else:
        a.root.mkdir(parents=True);value=dict(passed=False,runtime=runtime(),cases=[])
        try:
            for name,fn in [('documented_cli',documented),('receipt_capacity',lambda p:capacity(p,'receipts')),('logical_capacity',lambda p:capacity(p,'logical_bytes')),('bounded_cycles',sustained)]:
                row=dict(name=name,passed=False);value['cases'].append(row);t=time.monotonic()
                try:row['details']=fn(a.root/name);row['passed']=True
                finally:row['seconds']=time.monotonic()-t
            value['passed']=True
        finally:(a.root/'receipt.json').write_text(json.dumps(value,indent=2)+'\n')
    if a.action!='cases':(a.root/('prepared.json' if a.action=='prepare' else 'finished.json')).write_text(json.dumps(value,indent=2)+'\n')
if __name__=='__main__':main()
