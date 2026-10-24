"""Build a hash-verified external SQLite; no third-party source is redistributed."""
import argparse,hashlib,io,json,subprocess,urllib.request,zipfile
from pathlib import Path
URL='https://sqlite.org/2026/sqlite-amalgamation-3540100.zip'
C_SHA3='e2b869d3003b33c942b7dd7063604fbc53553e1b66609570df39b9b7b558ee81'

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();a.root.mkdir(parents=True,exist_ok=False)
    data=urllib.request.urlopen(URL,timeout=30).read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        code=z.read('sqlite-amalgamation-3540100/sqlite3.c')
    if hashlib.sha3_256(code).hexdigest()!=C_SHA3:raise ValueError('Official SQLite source hash mismatch')
    (a.root/'sqlite3.c').write_bytes(code)
    args=['gcc','-O2','-fPIC','-shared','-DSQLITE_THREADSAFE=1','-o',str(a.root/'libsqlite3.so.0'),str(a.root/'sqlite3.c'),'-ldl','-lpthread','-lm']
    subprocess.run(args,check=True,timeout=180)
    value=dict(url=URL,archive_sha256=hashlib.sha256(data).hexdigest(),source_sha3_256=C_SHA3,
               library_sha256=hashlib.sha256((a.root/'libsqlite3.so.0').read_bytes()).hexdigest(),
               compiler=subprocess.check_output(['gcc','--version'],text=True).splitlines()[0],flags=args[1:5])
    (a.root/'build.json').write_text(json.dumps(value,indent=2)+'\n')
    print(json.dumps(value))
if __name__=='__main__':main()
