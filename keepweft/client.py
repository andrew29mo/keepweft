"""Explicit saved envelopes; never automatically mint a new retry identity."""
import argparse
import json
import os
from pathlib import Path
import uuid
from .service import call
from .data import sync_dir

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['status','prepare','submit','lookup','cancel','rotate']);p.add_argument('--root',type=Path,required=True);p.add_argument('--envelope',type=Path);p.add_argument('--timeout',type=float,default=10)
    a=p.parse_args()
    if a.action=='status':reply=call(a.root,'status',{})
    elif a.action=='prepare':
        if a.envelope is None:p.error('--envelope required')
        status=call(a.root,'status',{})
        if not status['ok']:print(json.dumps(status));raise SystemExit(1)
        env=dict(**status['result']['namespace'],request_id=uuid.uuid4().hex,command=dict(kind='backup',timeout=a.timeout))
        # O_EXCL protects saved identities. Save+fsync before any submit.
        fd=os.open(a.envelope,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:f.write(json.dumps(env)+'\n');f.flush();os.fsync(f.fileno())
        sync_dir(a.envelope.parent);reply=dict(ok=True,result=env)
    else:
        if a.envelope is None:p.error('--envelope required, including for explicit rotate')
        env=json.loads(a.envelope.read_text())
        args={k:env[k] for k in ('epoch','generation')} if a.action=='rotate' else {k:env[k] for k in ('epoch','generation','request_id')} if a.action=='lookup' else env
        reply=call(a.root,a.action,args)
    print(json.dumps(reply,allow_nan=False));raise SystemExit(0 if reply['ok'] else 1)
if __name__=='__main__':main()
