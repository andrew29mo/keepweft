"""Synchronous exploration CLI; full daemon/scheduling remains MVP work."""
import argparse,json,sys
from pathlib import Path
from .core import Controller,diagnose
from .data import init_ledger,runtime

def main():
    p=argparse.ArgumentParser();p.add_argument('operation',choices=['init-source','backup','status','restore','release','delete','prune','runtime','diagnose'])
    p.add_argument('--root',type=Path);p.add_argument('--source',type=Path);p.add_argument('--uuid');p.add_argument('--count',type=int,default=0);p.add_argument('--id');p.add_argument('--options',type=Path);p.add_argument('--barriers',type=Path,help='explicit test-only scheduling barriers');p.add_argument('--timeout',type=float,default=10);p.add_argument('--cancel',type=Path);p.add_argument('--epoch',type=int);p.add_argument('--revision',type=int)
    a=p.parse_args()
    try:
        if a.operation=='runtime':result=runtime()
        elif a.operation=='diagnose':result=diagnose(a.root)
        elif a.operation=='init-source':result=dict(uuid=init_ledger(a.source,a.count))
        else:
            with Controller(a.root,a.source,a.uuid,json.loads(a.options.read_text()) if a.options else None,a.barriers) as c:
                token=dict(epoch=a.epoch,revision=a.revision) if a.epoch is not None or a.revision is not None else None
                if a.operation=='backup':result=c.backup(token,a.timeout,a.cancel)
                elif a.operation=='restore':result=c.restore(a.id,token,a.timeout)
                elif a.operation=='release':result=c.release(a.id,token)
                elif a.operation=='delete':result=c.delete(a.id,token)
                elif a.operation=='prune':result=c.prune(token)
                else:result=c.status()
        print(json.dumps(dict(ok=True,result=result),allow_nan=False))
    except Exception as exc:
        print(json.dumps(dict(ok=False,error=type(exc).__name__,detail=str(exc),sqlite_errorcode=getattr(exc,'sqlite_errorcode',None))))
        raise SystemExit(1)
if __name__=='__main__':main()
