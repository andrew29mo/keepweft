"""Bounded installed-service closeout. No restarts inside resource trial."""
import argparse
import contextlib
import hashlib
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
FD_QUIESCENCE_SECONDS=.25

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
        require(h.cli_reader('stop',rid)['exit_proven'],'CLI stop failed')
        stale_fences(h,rid,dict(epoch=h.inventory()['token']['epoch']-1))
        h.cli_reader('release',rid)
        require(h.pin(bid)==0 and not (h.root/'restores'/rid).exists(),'CLI release incomplete')
        mode=(h.root/'control.sock').stat().st_mode&0o777
        require(mode==0o600,'Socket permissions')
        h.stop();require(not (h.root/'control.sock').exists(),'Socket not removed')
        return dict(installed_cli=True,barriers=False,query_count=40,pin_after_release=0,socket_mode='0600',socket_removed=True,independent_stale_fences=True)
    finally:h.close()


def owned_service_snapshot(h):
    # Full control/catalog state, all backup contents and directory identities.
    # Global statvfs free space may move due to unrelated host activity.
    status=h.ok('status',{})
    status['inventory']['usage'].pop('filesystem_free_bytes')
    with contextlib.closing(sqlite3.connect('file:'+str(h.root/'catalog.sqlite')+'?mode=ro',uri=True)) as db:
        rows={t:db.execute('select * from '+t+' order by rowid').fetchall() for t in ('authority','ops','backups','restores','readers','requests','request_namespace')}
    files={str(p.relative_to(h.root/'backups')):('directory' if p.is_dir() else digest_file(p)) for p in (h.root/'backups').rglob('*')}
    return dict(status=status,catalog_rows=rows,backup_files=files)


def witness_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def stale_fences(h,rid,old):
    current=h.inventory()['token']
    require(old['epoch']<current['epoch'] and current['revision']>0,'No distinct stale authority')
    for token in (dict(epoch=old['epoch'],revision=current['revision']),dict(epoch=current['epoch'],revision=current['revision']-1)):
        before=owned_service_snapshot(h);reply=h.reject('release',rid,token)
        require(reply['detail']=='Explicit current epoch/revision required','Fence masked by unrelated refusal')
        require(owned_service_snapshot(h)==before,'Rejected authority changed owned state')

def capacity(path,kind):
    # Separate declared logical-byte vs receipt policies, no injected config mutation.
    opts=dict(artifact_bytes=262144,headroom_bytes=65536,keep=8)
    opts.update(dict(max_receipts=4) if kind=='receipts' else dict(budget_bytes=1300000))
    h=Closeout(path,opts)
    try:
        h.start();bid,rid=h.setup_copy();h.cmd('start',rid);h.track(rid)
        attempts=[]
        for _ in range(12):
            before=owned_service_snapshot(h);e=h.envelope();reply=call(h.root,'submit',e)
            attempts.append(dict(ok=reply['ok'],code=reply.get('code')))
            if not reply['ok']:
                require(reply['code']==('RECEIPT_FULL' if kind=='receipts' else 'Refused'),'Wrong capacity failure: '+str(reply))
                if kind=='logical_bytes':require(reply['detail']=='Capacity unavailable; previous backups preserved','Wrong space refusal')
                after=owned_service_snapshot(h)
                require(after==before,'Refusal changed owned status, backup files or catalog/receipt contents')
                break
            require(h.terminal(e)['state']=='AVAILABLE','Admitted operation unexpectedly failed')
        else:raise ValueError('Capacity was never reached')
        require(h.pin(bid)==1 and h.cmd('query',rid)['count']==40,'Capacity harmed active reader')
        require(h.cmd('stop',rid)['exit_proven'],'Full store prevented stop');h.cmd('release',rid)
        require(h.pin(bid)==0 and not (h.root/'restores'/rid).exists(),'Full store prevented release')
        return dict(refusal_witness_before_sha256=witness_hash(before),refusal_witness_after_sha256=witness_hash(after),all_backup_files_and_catalog_compared=True,kind=kind,options=opts,attempts=attempts,refusal_code=attempts[-1]['code'],inventory_preserved_on_refusal=True,receipts_preserved_on_refusal=True,query_at_full=40,pin_before_stop=1,stop_exit_proven=True,pin_after_release=0,logical_bytes_after_release=h.inventory()['usage']['logical_bytes'])
    finally:h.close()


def fd_observations(pid):
    # A completed RPC can reach its client just before Service.drop closes the
    # accepted socket. Observe actual kernel socket state, not an arbitrary
    # preferred minimum FD count. A persistent regular-file FD leak is not hidden.
    start=time.monotonic();values=[]
    while True:
        directory=Path('/proc/'+str(pid)+'/fd');names=list(directory.iterdir());links={}
        for p in names:
            try:links[p.name]=os.readlink(p)
            except FileNotFoundError:links[p.name]='<closed-during-observation>'
        unix={line.split()[6]:int(line.split()[3],16) for line in Path('/proc/'+str(pid)+'/net/unix').read_text().splitlines()[1:] if len(line.split())>=7}
        sockets=[target[8:-1] for target in links.values() if target.startswith('socket:[')]
        pending=sum(not (unix.get(inode,0)&0x10000) for inode in sockets)
        elapsed=time.monotonic()-start
        values.append(dict(seconds=elapsed,fds=len(names),non_listener_sockets=pending,targets=links,unix_socket_flags={inode:unix.get(inode) for inode in sockets}))
        stable=elapsed<=FD_QUIESCENCE_SECONDS and len(values)>=2 and values[-1]['fds']==values[-2]['fds'] and values[-1]['non_listener_sockets']==values[-2]['non_listener_sockets']==0 and all('<closed-during-observation>' not in o['targets'].values() for o in values[-2:])
        if stable or elapsed>=FD_QUIESCENCE_SECONDS:
            return dict(fds=len(names),fd_quiescent=stable,fd_observations=values)
        time.sleep(.01)


def validate_fd_observations(s):
    require(s['fd_quiescent'] is True and len(s['fd_observations'])>=2,'No quiescent FD evidence')
    previous=-1
    for o in s['fd_observations']:
        require(type(o['seconds']) in (int,float) and not isinstance(o['seconds'],bool) and 0<=o['seconds']<.5 and o['seconds']>=previous,'Invalid FD observation time')
        require(type(o['fds']) is int and o['fds']>0 and type(o['non_listener_sockets']) is int and o['non_listener_sockets']>=0,'Invalid FD observation')
        require(type(o['targets']) is dict and len(o['targets'])==o['fds'] and all(type(t) is str for t in o['targets'].values()),'Missing FD targets')
        sockets={t[8:-1] for t in o['targets'].values() if t.startswith('socket:[')}
        flags=o['unix_socket_flags']
        require(type(flags) is dict and set(flags)==sockets and all(f is None or (type(f) is int and f>=0) for f in flags.values()),'Missing socket flags')
        require(sum(f is None or not(f&0x10000) for f in flags.values())==o['non_listener_sockets'],'Socket classification mismatch')
        previous=o['seconds']
    require(s['fd_observations'][-1]['seconds']<=FD_QUIESCENCE_SECONDS,'FD quiescence exceeded deadline')
    require(all(o['fds']==s['fds'] and o['non_listener_sockets']==0 for o in s['fd_observations'][-2:]),'Pending RPC socket or changing FD count')


def sample(h,cycle):
    with contextlib.closing(sqlite3.connect('file:'+str(h.root/'catalog.sqlite')+'?mode=ro',uri=True)) as db:
        rows={t:db.execute('select count(*) from '+t).fetchone()[0] for t in ('ops','requests','backups','restores','readers')}
        active=db.execute("select count(*) from restores where state!='RELEASED'").fetchone()[0]
        pins=db.execute('select coalesce(sum(pins),0) from backups').fetchone()[0]
    pid=h.proc.pid;children=Path('/proc/'+str(pid)+'/task/'+str(pid)+'/children').read_text().split()
    st=h.ok('status',{})
    descriptors=fd_observations(pid)
    return dict(**descriptors,cycle=cycle,pid=pid,rss_kib=rss(pid),children=len(children),rows=rows,active_restores=active,pins=pins,guards=len(list((h.root/'guards').glob('*'))),files=sum(p.is_file() for p in h.root.rglob('*')),catalog_bytes=(h.root/'catalog.sqlite').stat().st_size,log_bytes=(h.p/'service.log').stat().st_size,**{k:st['inventory']['usage'][k] for k in ('logical_bytes','allocated_bytes')})


def validate_samples(samples,cycles=CYCLES):
    require(type(samples) is list and len(samples)==cycles+1,'Missing resource observation')
    for s in samples:
        validate_fd_observations(s)
        for k in ('cycle','pid','rss_kib','fds','children','active_restores','pins','guards','files','catalog_bytes','log_bytes','logical_bytes','allocated_bytes'):
            require(type(s[k]) is int and s[k]>=0,'Invalid integer resource observation: '+k)
        require(s['pid']>0 and s['rss_kib']>0 and s['fds']>0 and s['catalog_bytes']>0 and s['logical_bytes']>=s['catalog_bytes'],'Impossible process/store observation')
        for k in ('ops','requests','backups','restores','readers'):
            require(type(s['rows'][k]) is int and s['rows'][k]>=0,'Invalid catalog count')
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
        def persist_samples():
            tmp=h.p/'resource-observations.next'
            tmp.write_text(json.dumps(dict(samples=samples,cycle_seconds=latencies,fd_quiescence_seconds=FD_QUIESCENCE_SECONDS),indent=2)+'\n')
            os.replace(tmp,h.p/'resource-observations.json')
        persist_samples()
        for cycle in range(1,CYCLES+1):
            t=time.monotonic();bid,rid=h.setup_copy();h.cmd('start',rid)
            require(h.cmd('query',rid)['count']==40,'Repeated query mismatch')
            time.sleep(READER_DWELL_SECONDS)
            require(h.cmd('query',rid)['count']==40,'Held reader query mismatch')
            require(h.cmd('stop',rid)['exit_proven'],'Repeated stop failed');h.cmd('release',rid)
            latencies.append(time.monotonic()-t);samples.append(sample(h,cycle));persist_samples()
        validate_samples(samples)
        return dict(fd_quiescence_seconds=FD_QUIESCENCE_SECONDS,cycles=CYCLES,reader_dwell_seconds=READER_DWELL_SECONDS,ledger_rows=40,restarts=0,warmup_cycles=4,rss_drift_allowance_kib=RSS_DRIFT_KIB,samples=samples,cycle_seconds=latencies,seconds=time.monotonic()-started,retained_metadata_explained=True,long_term_qualification=False)
    finally:h.close()


def catalog_snapshot(root):
    # Read-only, no formal controller: must not advance epoch/reconcile before witness.
    p=root/'catalog.sqlite'
    with contextlib.closing(sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True)) as db:
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
        stale_fences(h,w['rid'],w['old_token'])
        if want=='READY':
            require(h.pin(w['bid'])==1,'Recovered live reference lost');h.cmd('start',w['rid']);h.track(w['rid']);require(h.cmd('query',w['rid'])['count']==40,'Reboot query wrong');require(h.cmd('stop',w['rid'])['exit_proven'],'Reboot stop failed');h.cmd('release',w['rid'])
        require(h.pin(w['bid'])==0 and not (root/'restores'/w['rid']).exists(),'Reboot release/pin failed')
        return dict(kind=w['kind'],boot_before=w['boot_before'],boot_after=boot_id(),journal_before=w['before'],journal_after_before_controller=observed,copy_hash_preserved_before_recovery=True,controller_killed_before_reboot=True,state_after_recovery=want,old_epoch_rejected=True,stale_epoch_only_rejected=True,stale_revision_only_rejected=True,stale_rejections_preserved_state=True,query_count=40 if want=='READY' else None,pin_after_release=0)
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
                except BaseException as exc:
                    row['error']=type(exc).__name__+': '+str(exc);raise
                finally:row['seconds']=time.monotonic()-t
            value['passed']=True
        finally:(a.root/'receipt.json').write_text(json.dumps(value,indent=2)+'\n')
    if a.action!='cases':(a.root/('prepared.json' if a.action=='prepare' else 'finished.json')).write_text(json.dumps(value,indent=2)+'\n')
if __name__=='__main__':main()
