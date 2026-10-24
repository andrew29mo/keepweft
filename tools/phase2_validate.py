"""Own a fresh no-mount Colima VM, install wheel, run probes, delete owned disks."""
import argparse,base64,datetime,hashlib,io,json,os,secrets,signal,subprocess,sys,tarfile,time,zipfile
from pathlib import Path
from .evidence import ROOT,manifest,fingerprint
from .phase2_report import verify,controls,render

def main():
    if not __debug__:raise RuntimeError('Validation requires normal Python')
    p=argparse.ArgumentParser();p.add_argument('--colima-home',type=Path,required=True);p.add_argument('--toolchain',type=Path,required=True);p.add_argument('--profile',required=True);p.add_argument('--wheel',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if not a.profile.startswith('keepweft-exp-') or not all(c.isalnum() or c=='-' for c in a.profile):p.error('Dedicated keepweft-exp-* profile required')
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()):p.error('Fresh output directory required')
    logs=out/'private-logs';logs.mkdir();source=manifest();wheel=a.wheel.resolve()
    with zipfile.ZipFile(wheel) as z:product={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith('keepweft/') and n.endswith('.py')}
    matches=product=={n:h for n,h in source.items() if n.startswith('keepweft/')}
    if not matches:raise ValueError('Build a wheel from the current source')
    v=dict(passed=False,run_id=secrets.token_hex(8),recorded_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source=source,source_sha256=fingerprint(source),source_changed=False,stages=[],wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),wheel_product_matches=matches,host_mounts='none')
    env=dict(os.environ,COLIMA_HOME=str(a.colima_home.resolve()),PATH=str(a.toolchain.resolve())+os.pathsep+os.environ.get('PATH',''));colima=a.toolchain.resolve()/'colima';remote='/opt/keepweft';created=False;initial=[]
    def persist():
        (out/'evidence.json').write_text(json.dumps(v,indent=2,allow_nan=False)+'\n');(out/'report.html').write_text(render(v))
    def execute(name,args,timeout=60,stdin=None):
        start=time.monotonic();proc=subprocess.Popen(list(map(str,args)),cwd=ROOT,env=env,text=True,stdin=subprocess.PIPE if stdin is not None else None,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True);timed=False
        try:stdout,stderr=proc.communicate(stdin,timeout=timeout)
        except subprocess.TimeoutExpired:
            timed=True;os.killpg(proc.pid,signal.SIGKILL);stdout,stderr=proc.communicate(timeout=5)
        except BaseException:
            os.killpg(proc.pid,signal.SIGKILL);stdout,stderr=proc.communicate(timeout=5);v['stages'].append(dict(name=name,exit_code=proc.returncode,timed_out=False,interrupted=True,seconds=time.monotonic()-start));persist();raise
        (logs/(name+'.log')).write_text(stdout+stderr);v['stages'].append(dict(name=name,exit_code=proc.returncode,timed_out=timed,seconds=time.monotonic()-start));persist()
        if timed or proc.returncode:raise RuntimeError(name+' failed or timed out')
        return stdout
    def ssh(name,args,**kw):return execute(name,[colima,'--profile',a.profile,'ssh','--',*args],**kw)
    def py(args):return ['sudo','env','LD_LIBRARY_PATH='+remote+'/runtime','python3',*args]
    try:
        initial=[json.loads(line) for line in execute('initial',[colima,'list','--json']).splitlines()]
        disk=a.colima_home.resolve()/'_lima/_disks'/('colima-'+a.profile)
        if any(r['name']==a.profile for r in initial) or disk.exists():raise RuntimeError('Refusing existing profile or retained data disk')
        v.update(fresh_profile=True,initial_disk_absent=True);created=True
        execute('create',[colima,'start',a.profile,'--cpu','2','--memory','3','--disk','15','--mount','none','--activate=false','--ssh-config=false','--hostname','keepweft-phase2','--dns-host','keepweft-phase2=127.0.0.1','--dns-host','lima-colima-'+a.profile+'=127.0.0.1'],timeout=300)
        ssh('dependencies',['sudo','sh','-c','apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-pip gcc libc6-dev e2fsprogs util-linux'],timeout=480)
        buf=io.BytesIO()
        with tarfile.open(fileobj=buf,mode='w:gz') as tar:
            for f in source:tar.add(ROOT/f,arcname='source/'+f,recursive=False)
            tar.add(wheel,arcname=wheel.name,recursive=False)
        code='import pathlib,sys,tarfile,io,base64;p=pathlib.Path(sys.argv[1]);p.mkdir(mode=0o700);tarfile.open(fileobj=io.BytesIO(base64.b64decode(sys.stdin.read()))).extractall(p,filter="data")'
        ssh('upload',['sudo','python3','-c',code,remote],stdin=base64.b64encode(buf.getvalue()).decode())
        ssh('runtime',['sudo','python3',remote+'/source/tools/build_sqlite.py','--root',remote+'/runtime'],timeout=240)
        v['sqlite_build']=json.loads(ssh_read_raw(colima,a.profile,env,remote+'/runtime/build.json'))
        install='python3 -I -c \'import importlib.util; assert importlib.util.find_spec("keepweft") is None\' && python3 -m pip install --break-system-packages --no-deps --no-index '+remote+'/'+wheel.name+' && mv '+remote+'/source/keepweft '+remote+'/retired-product-source'
        ssh('install',['sudo','sh','-c',install],timeout=90)
        provenance='import keepweft,pathlib,hashlib,json,sqlite3; from keepweft.data import runtime; p=pathlib.Path(keepweft.__file__).resolve().parent; lib=pathlib.Path("'+remote+'/runtime/libsqlite3.so.0"); maps=pathlib.Path("/proc/self/maps").read_text(); assert str(lib) in maps; print(json.dumps(dict(location=str(p),modules={"keepweft/"+str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob("*.py")},source_package_absent=not pathlib.Path("'+remote+'/source/keepweft").exists(),runtime=runtime(),library_sha256=hashlib.sha256(lib.read_bytes()).hexdigest())))'
        v['provenance']=json.loads(ssh('provenance',py(['-I','-c',provenance])))
        execute('native',[sys.executable,'-m','tools.unit','--output',out/'native-unit.json']);v['native_unit']=json.loads((out/'native-unit.json').read_text())
        ssh('linux',['sudo','sh','-c','cd '+remote+'/source && LD_LIBRARY_PATH='+remote+'/runtime python3 -m tools.unit --output '+remote+'/linux-unit.json'])
        v['linux_unit']=json.loads(ssh('linux-read',['sudo','cat',remote+'/linux-unit.json']));(out/'linux-unit.json').write_text(json.dumps(v['linux_unit'],indent=2)+'\n')
        ssh('explore',['sudo','sh','-c','cd '+remote+'/source && LD_LIBRARY_PATH='+remote+'/runtime python3 -m tools.phase2_cases --root '+remote+'/cases --source-sha '+v['source_sha256']],timeout=240)
        v['guest']=json.loads(ssh('guest-read',['sudo','cat',remote+'/cases/evidence.json']));v['passed']=True
    except BaseException as exc:
        v['error']=type(exc).__name__+': '+str(exc).replace(str(ROOT),'<checkout>')
        if created:
            try:v['guest']=json.loads(ssh('failed-guest',['sudo','cat',remote+'/cases/evidence.json']))
            except BaseException:pass
    finally:
        if created:
            try:
                execute('delete',[colima,'delete',a.profile,'--data','--force'],timeout=150)
                final=[json.loads(line) for line in execute('final',[colima,'list','--json']).splitlines()]
                v['vm_final']='Deleted' if not any(r['name']==a.profile for r in final) else 'Retained';v['data_disk_removed']=not disk.exists()
                v['preexisting_profiles_unchanged']=all(any(q['name']==r['name'] and q['status']==r['status'] for q in final) for r in initial)
            except BaseException as exc:v.update(passed=False,cleanup_error=type(exc).__name__+': '+str(exc))
        v['source_changed']=manifest()!=source
        if v['passed']:
            try:verify(v);v['controls']=controls(v)
            except BaseException as exc:v.update(passed=False,verification_error=type(exc).__name__+': '+str(exc))
        persist()
    print(json.dumps({k:v.get(k) for k in ('passed','run_id','error','verification_error','cleanup_error','vm_final')}));raise SystemExit(0 if v['passed'] else 1)

def ssh_read_raw(colima,profile,env,path):
    # Auxiliary build receipt read, with bounded exit status. Not a product test stage.
    return subprocess.check_output([str(colima),'--profile',profile,'ssh','--','sudo','cat',path],env=env,text=True,timeout=20)
if __name__=='__main__':main()
