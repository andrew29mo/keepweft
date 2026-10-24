"""Exec-only worker; inherited lifetime lock closes on exit, never explicitly unlocks."""
import atexit
import json
import os
from pathlib import Path
import sys
from .data import copy_snapshot,dump,checkpoint

def main():
    job=json.loads(Path(sys.argv[1]).read_text());fd=job['lock_fd']
    os.fstat(fd)  # Fail if the kernel lock descriptor was not actually inherited.
    if job['barriers']:
        atexit.register(checkpoint,job['barriers'],'process_exit',job['deadline'])
    try:
        copy_snapshot(job['source'],job['stage'],job['expected_uuid'],job['deadline'],
                      job['max_bytes'],job['wal_growth_limit'],job['barriers'],
                      lambda:bool(job['cancel_path'] and Path(job['cancel_path']).exists()))
    except BaseException as exc:
        error=dict(error=(type(exc).__name__+': '+str(exc))[:2000],sqlite_errorcode=getattr(exc,'sqlite_errorcode',None))
        print(json.dumps(error),file=sys.stderr,flush=True)
        try:dump(Path(job['stage'])/'error.json',error)
        except BaseException:pass
        raise SystemExit(1)
    # Intentionally retain fd through interpreter/atexit shutdown. The kernel
    # closes it at process exit; early close would allow takeover before exit.

if __name__=='__main__':main()
