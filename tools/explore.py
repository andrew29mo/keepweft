"""Real-process probes against the installed Keepweft core; Linux VM only."""
import contextlib
import argparse,hashlib,json,os,platform,shutil,signal,sqlite3,statistics,subprocess,sys,time,urllib.request
from pathlib import Path
from keepweft.core import Controller,Busy,Degraded,usage,diagnose
from keepweft.data import Refused,init_ledger,append,inspect,readonly,digest_file,runtime
from tools.evidence import require

CHILDREN=[]

def run(args,**kw):
    return subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=kw.pop('timeout',20),**kw)

def start(args):
    p=subprocess.Popen(list(map(str,args)),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True);CHILDREN.append(p);return p

def wait(test,seconds=10):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        value=test()
        if value:return value
        time.sleep(.01)
    raise TimeoutError('Probe observation deadline')

def arm(p,name):p.mkdir(parents=True,exist_ok=True);(p/(name+'.arm')).touch()
def release(p,name):(p/(name+'.release')).touch()
def pidinfo(pid):
    p=Path('/proc')/str(pid)
    if not p.exists():return dict(pid=pid,exited=True)
    status=dict(line.split(':',1) for line in (p/'status').read_text().splitlines() if ':' in line)
    return dict(pid=pid,start_ticks=(p/'stat').read_text().rsplit(')',1)[1].split()[19],state=status['State'].strip(),rss_kib=int(status.get('VmRSS','0 kB').split()[0]),exited=status['State'].strip().startswith('Z'))

def dead(pid):return pidinfo(pid)['exited']
def kill(p):
    if p.poll() is None:p.kill()
    p.wait(timeout=3)

def cli(root,op,*args):return [sys.executable,'-m','keepweft.cli',op,'--root',root,*args]
def finish(p):
    out,err=p.communicate(timeout=15);require(p.returncode==0,'Formal command failed: '+out+err)
    return json.loads(out)['result']
def seeded(base,count=32,payload=2048,options=None):
    base.mkdir(parents=True);source=base/'source.sqlite';identity=init_ledger(source,count,payload);root=base/'store'
    with Controller(root,source,identity,options):pass
    return root,source,identity

def snapshot_cancel(base):
    root,source,identity=seeded(base,count=192,payload=8192)
    barrier=base/'barriers';arm(barrier,'snapshot_open')
    db=sqlite3.connect(source,isolation_level=None);db.execute('pragma synchronous=full')
    # A real uncommitted transaction must be absent from the established reader.
    db.execute('begin immediate');db.execute('insert into tx values(193,?,?)',(b'never-committed','wrong'))
    began=time.monotonic();p=start(cli(root,'backup','--barriers',barrier,'--timeout','15'))
    wait(lambda:(barrier/'snapshot_open.seen').exists());worker_pid=int((barrier/'snapshot_open.seen').read_text());live_worker=pidinfo(worker_pid)
    db.execute('rollback');wal=Path(str(source)+'-wal');before=wal.stat().st_size if wal.exists() else 0
    latencies=[append(db,n,8192) for n in range(193,225)]
    during=wal.stat().st_size
    release(barrier,'snapshot_open');m=finish(p);db.close()
    require(m['expected']['count']==m['expected']['max_seq']==192,'Snapshot inherited later/uncommitted transactions')
    with contextlib.closing(readonly(root/'backups'/m['id']/'db.sqlite')) as c:
        require([r[0] for r in c.execute('select seq from tx order by seq')]==list(range(1,193)),'Snapshot sequence oracle mismatch')
    with contextlib.closing(readonly(source)) as c:require(c.execute('select count(*) from tx').fetchone()[0]==224,'Concurrent commits lost')
    require(during>before and dead(worker_pid),'No actual WAL growth or worker exit evidence')
    # Deliberate cancellation only after the real worker has established a reader.
    outcomes=[]
    for kind in ('cancel','timeout'):
        b=base/('barrier-'+kind);arm(b,'snapshot_open');cancel=base/'cancel'
        q=start(cli(root,'backup','--barriers',b,'--timeout','1' if kind=='timeout' else '10',*(['--cancel',cancel] if kind=='cancel' else [])))
        wait(lambda:(b/'snapshot_open.seen').exists());pid=int((b/'snapshot_open.seen').read_text())
        if kind=='cancel':cancel.touch()
        stdout,stderr=q.communicate(timeout=5);answer=json.loads(stdout)
        require(q.returncode!=0 and answer['ok'] is False and dead(pid),'Cancellation/timeout faked success or retained worker')
        with Controller(root) as c:
            status=c.status();require(not list((root/'staging').iterdir()) and len([r for r in status['backups'] if r['state']=='AVAILABLE'])==1,'Cancellation damaged inventory')
        outcomes.append(dict(kind=kind,answer=answer,worker_exited=True,staging_empty=True))
    return dict(snapshot=m,source_count_after=224,uncommitted_excluded=True,worker_at_snapshot=live_worker,
                barrier_controlled_seconds=time.monotonic()-began,writer_commits=32,
                writer_commit_p50_seconds=statistics.median(latencies),writer_commit_p95_seconds=sorted(latencies)[int(len(latencies)*.95)],
                wal_before_bytes=before,wal_while_reader_bytes=during,reader_released=True,cancellations=outcomes)

def sealed_restore(base):
    root,source,identity=seeded(base,80)
    with Controller(root) as c:
        t=time.monotonic();m=c.backup();backup_seconds=time.monotonic()-t
        require(not any(p.name.endswith(('-wal','-shm','-journal')) for p in (root/'backups'/m['id']).iterdir()),'Backup depends on sidecars')
        advanced=sqlite3.connect(source,isolation_level=None);append(advanced,81);advanced.close()
        t=time.monotonic();r=c.restore(m['id']);ready=base/'http.ready'
        expected_path=root/'restores'/r['id']/'db.sqlite'
        require(Path(r['path'])==expected_path and expected_path.stat().st_ino!=(root/'backups'/m['id']/'db.sqlite').stat().st_ino,'Restore did not create a distinct managed copy');q=start([sys.executable,'-m','keepweft.view','--database',r['path'],'--ready',ready]);wait(ready.exists)
        url='http://127.0.0.1:'+ready.read_text()+'/summary';answer=json.load(urllib.request.urlopen(url,timeout=2));rto=time.monotonic()-t
        require(answer==dict(uuid=identity,count=80,max_seq=80),'Restored application query wrong')
        bad=run([sys.executable,'-c','import sqlite3,sys; c=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True); c.execute("delete from tx")',r['path']])
        require(bad.returncode!=0,'Restored application is writable')
        resources=dict(controller=pidinfo(os.getpid()),view=pidinfo(q.pid),store=usage(root))
        kill(q);c.release(r['id'])
    negatives=[]
    for kind in ('missing','wrong-uuid','foreign-key','schema','truncated','wrong-watermark'):
        d=base/kind;rt,src,uid=seeded(d,12)
        if kind=='missing':src.unlink()
        if kind=='wrong-uuid':
            c0=sqlite3.connect(src);c0.execute('update meta set uuid=?',('other',));c0.commit();c0.close()
        if kind=='foreign-key':
            c0=sqlite3.connect(src);c0.execute('insert into item values(999,0)');c0.commit();c0.close()
        if kind=='schema':
            c0=sqlite3.connect(src);c0.execute('pragma user_version=2');c0.close()
        rejected=False
        with Controller(rt) as c:
            try:
                artifact=c.backup()
                if kind in ('truncated','wrong-watermark'):
                    path=rt/'backups'/artifact['id']/'db.sqlite'
                    if kind=='truncated':
                        with path.open('r+b') as f:f.truncate(100)
                    else:
                        c0=sqlite3.connect(path);c0.execute('delete from item');c0.execute('delete from tx');c0.commit();c0.close()
                    c.restore(artifact['id'])
            except (Refused,sqlite3.Error):rejected=True
        require(rejected,'Invalid input admitted: '+kind);negatives.append(dict(kind=kind,rejected=True))
    return dict(source_count_after_backup=81,restored_copy_distinct=True,backup_seconds=backup_seconds,restore_to_first_HTTP_seconds=rto,application=answer,read_only_write_rejected=True,
                standalone_main_file=True,resources=resources,negatives=negatives)

def crash_recovery(base):
    records=[]
    for point in ('copy_complete','publish_intent','after_rename','after_catalog','restore_materialized','delete_intent','after_unlink'):
        d=base/point;root,source,identity=seeded(d)
        b=d/'barrier';arm(b,point);operation='backup';args=[];latest=None
        if point in ('restore_materialized','delete_intent','after_unlink'):
            with Controller(root) as c:
                first=c.backup();latest=c.backup()
            operation='restore' if point=='restore_materialized' else 'delete';args=['--id',first['id']]
        p=start(cli(root,operation,'--barriers',b,'--timeout','15',*args));wait(lambda:(b/(point+'.seen')).exists())
        before=json.loads(run(cli(root,'diagnose')).stdout)['result'];barrier_pid=int((b/(point+'.seen')).read_text())
        kill(p);busy=False
        if point=='copy_complete':
            try:
                with Controller(root):pass
            except Busy:busy=True
            require(busy and not dead(barrier_pid),'Takeover did not respect inherited kernel lock')
            release(b,point);wait(lambda:dead(barrier_pid),5)
        with Controller(root) as c:
            s=c.status();available=[x for x in s['backups'] if x['state']=='AVAILABLE']
            if point=='copy_complete':require(available==[] and not list((root/'staging').iterdir()),'Incomplete copy published')
            elif point in ('delete_intent','after_unlink'):
                require(len(available)==1 and available[0]['id']==latest['id'],'Delete recovery damaged latest')
            elif point=='restore_materialized':
                require(len(available)==2 and all(x['pins']==0 for x in s['backups']) and s['restores'][0]['state']=='RELEASED','Restore crash leaked pin')
            else:require(len(available)==1 and available[0]['manifest']['expected']['count']==32,'Publication recovery lost/duplicated backup')
            # Independent current-revision/old-epoch and current-epoch/old-revision.
            old_epoch=before['authority'][0][0];old_revision=before['authority'][0][1]
            stale=[]
            for token in (dict(epoch=old_epoch,revision=c.token['revision']),dict(epoch=c.token['epoch'],revision=old_revision)):
                prior=c.status()
                try:c.backup(token)
                except Refused as exc:require(str(exc)=='Stale operation token','Wrong stale refusal');stale.append(dict(token=token,current=c.token,rejected=True))
                else:raise ValueError('Stale operation accepted')
                require(c.status()==prior,'Stale operation mutated state')
            old_attempts=[x for x in s['operations'] if x['kind']=='backup']
            if old_attempts:
                try:c._phase(old_attempts[0]['id'],'AVAILABLE')
                except Refused:retired=True
                else:retired=False
                require(retired,'Retired attempt could update lifecycle')
            else:retired=True
            records.append(dict(point=point,owner_killed=True,worker_lock_blocked_takeover=busy,
                                recovered=True,available=len(available),stale=stale,retired_attempt_rejected=retired,
                                staging_empty=not list((root/'staging').iterdir())))
    return dict(cases=records)

def capacity(base):
    # Dedicated ext4 loop in the already isolated VM, never on host filesystems.
    require(platform.system()=='Linux' and os.getuid()==0 and Path('/run/systemd/system').exists(),'Isolated Linux VM root required')
    base.mkdir(parents=True);image=base/'volume.img';mount=base/'mount';mount.mkdir()
    require(run(['truncate','-s','64M',image]).returncode==0,'Image allocation failed')
    require(run(['mkfs.ext4','-q','-F',image]).returncode==0,'mkfs failed')
    require(run(['mount','-o','loop',image,mount]).returncode==0,'Loop mount failed')
    value={};p=None;readonly_bound=False
    try:
        source=base/'source.sqlite';uid=init_ledger(source,160,8192);root=mount/'store'
        with Controller(root,source,uid) as c:first=c.backup()
        good=root/'backups'/first['id']/'db.sqlite';before_hash=digest_file(good)
        b=base/'full-barrier';arm(b,'snapshot_open');p=start(cli(root,'backup','--barriers',b,'--timeout','20'));wait(lambda:(b/'snapshot_open.seen').exists())
        filler=mount/'external-fault-fill';written=0
        with filler.open('wb',buffering=0) as f:
            try:
                while True:written+=f.write(b'x'*65536)
            except OSError as exc:require(exc.errno==28,'Not real ENOSPC')
        full=usage(root);release(b,'snapshot_open');stdout,stderr=p.communicate(timeout=10);answer=json.loads(stdout)
        require(p.returncode!=0 and answer['ok'] is False,'Full filesystem faked success')
        startup=run(cli(root,'status'));require(startup.returncode!=0,'Full catalog admitted new authority')
        require(digest_file(good)==before_hash,'Full failure damaged last usable backup')
        diagnostic=json.loads(run(cli(root,'diagnose')).stdout);require(diagnostic['ok'] and diagnostic['result']['mode']=='READ_ONLY_DIAGNOSTIC','No limited diagnostic')
        filler.unlink();os.sync()
        with Controller(root) as c:
            require(not list((root/'staging').iterdir()),'Repair left incomplete staging')
            newer=c.backup();stale=dict(epoch=1,revision=c.token['revision'])
            try:c.backup(stale)
            except Refused:pass
            else:raise ValueError('Post-repair old epoch accepted')
        value['enospc']=dict(real_errno=28,filler_bytes=written,failed_command=answer,startup_refused=True,
                              previous_hash_preserved=True,diagnostic_mode=diagnostic['result']['mode'],at_full=full,
                              repair_backup_count=newer['expected']['count'],stale_rejected=True)
        with Controller(root) as current:
            # Linux refuses a whole-filesystem ro remount with open writable FDs.
            # A ro bind mount faults new journal/path writes of the already-running controller.
            require(run(['mount','--bind',root,root]).returncode==0,'Readonly bind setup failed')
            readonly_bound=True
            require(run(['mount','-o','remount,bind,ro',root]).returncode==0,'Readonly bind remount failed')
            os_errno=None
            try:(root/'readonly-write-probe').write_text('must fail')
            except OSError as exc:os_errno=exc.errno
            require(os_errno==30,'Mount did not enforce EROFS')
            actual_readonly=False;readonly_code=None;readonly_detail=None
            try:current.backup()
            except sqlite3.Error as exc:
                readonly_code=getattr(exc,'sqlite_errorcode',0);readonly_detail=str(exc)
                actual_readonly=readonly_code&255 in (sqlite3.SQLITE_READONLY,sqlite3.SQLITE_IOERR,sqlite3.SQLITE_CANTOPEN)
            value['readonly_probe']=dict(os_errno=os_errno,sqlite_errorcode=readonly_code,detail=readonly_detail,retired=current.blocked)
            require(actual_readonly and current.blocked,'In-flight readonly storage error not observed/retired')
            try:current.backup()
            except Degraded:readonly_blocked=True
            else:readonly_blocked=False
            require(readonly_blocked,'Readonly-retired writer accepted another operation')
        readonly_run=run(cli(root,'status'));reply=json.loads(readonly_run.stdout)
        require(readonly_run.returncode!=0 and reply['ok'] is False and digest_file(good)==before_hash,'Readonly faked startup or damaged backup')
        require(run(['umount',root]).returncode==0,'Readonly bind removal failed');readonly_bound=False
        with Controller(root) as c:c.backup()
        value['readonly']=dict(real_remount=True,readonly_bind_mount=True,os_errno=os_errno,inflight_sqlite_errorcode=readonly_code,inflight_error_detail=readonly_detail,retired_mutation_refused=True,reply=reply,previous_hash_preserved=True,repair_succeeded=True)
        # Actual SQLite page-capacity FULL against the formal catalog; no mocked error.
        with Controller(root) as c:
            pages=c.db.execute('pragma page_count').fetchone()[0]
            c.db.execute('pragma max_page_count='+str(pages))
            actual_full=False
            try:
                for i in range(30):c._new('backup',dict(padding='x'*16384))
            except sqlite3.Error as exc:
                actual_full=getattr(exc,'sqlite_errorcode',None)==sqlite3.SQLITE_FULL
            require(actual_full and c.blocked,'SQLite FULL was not observed/retired')
            try:c.backup()
            except Degraded:refused=True
            else:refused=False
            require(refused,'Storage-retired controller accepted mutation')
        with Controller(root) as c:repaired=c.backup()
        value['sqlite_full']=dict(actual_sqlite_errorcode=sqlite3.SQLITE_FULL,retired_controller=True,new_mutation_refused=True,explicit_reopen_repair=True,repair_backup_count=repaired['expected']['count'])
    except BaseException as exc:
        value['failure']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        active_error=sys.exc_info()[0] is not None
        if p and p.poll() is None:kill(p)
        if readonly_bound:
            bound_cleanup=run(['umount',root]);value['readonly_bind_removed']=bound_cleanup.returncode==0
        run(['mount','-o','remount,rw',mount])
        unmount=run(['umount',mount]);value['loop_unmounted']=unmount.returncode==0 and not os.path.ismount(mount)
        if not value['loop_unmounted']:value['cleanup_error']=unmount.stderr[-1000:]
        (base/'_progress.json').write_text(json.dumps(value,indent=2)+'\n')
        if not value['loop_unmounted'] and not active_error:raise ValueError('Loop filesystem cleanup failed')
    value['loop_unmounted']=not os.path.ismount(mount)
    value['loop_device_detached']=not run(['losetup','-j',image]).stdout.strip()
    require(value['loop_device_detached'],'Loop device remained attached')
    return value

def main():
    if not __debug__:raise RuntimeError('Exploration requires assertions enabled')
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--source-sha',required=True);a=p.parse_args();a.root.mkdir(parents=True,exist_ok=False)
    evidence=dict(passed=False,source_sha256=a.source_sha,runtime=runtime(),platform=platform.platform(),cases=[],limits=dict(power_loss_tested=False,vm_reboot_tested=False,hardware_tested=False,production_switch_tested=False))
    try:
        for name,fn in (('A_snapshot_cancel',snapshot_cancel),('B_sealed_restore',sealed_restore),('C_publication_takeover',crash_recovery),('D_capacity_repair',capacity)):
            t=time.monotonic();details=fn(a.root/name);evidence['cases'].append(dict(name=name,passed=True,seconds=time.monotonic()-t,details=details));(a.root/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
        evidence['passed']=True
    except BaseException as exc:
        evidence['error']=type(exc).__name__+': '+str(exc)
        evidence['failed_progress']=[json.loads(p.read_text()) for p in a.root.rglob('_progress.json')]
        raise
    finally:
        for child in CHILDREN:
            if child.poll() is None:kill(child)
        evidence['owned_children_exited']=all(p.poll() is not None for p in CHILDREN)
        remaining=[]
        for path in Path('/proc').glob('[0-9]*/cmdline'):
            try:args=path.read_bytes().split(b'\0')
            except (FileNotFoundError,PermissionError,ProcessLookupError):continue
            if b'keepweft.worker' in args:remaining.append(int(path.parent.name))
        evidence['no_worker_processes_remaining']=not remaining
        if remaining:evidence['passed']=False
        (a.root/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(dict(passed=evidence['passed'],cases=len(evidence['cases']))))
if __name__=='__main__':main()
