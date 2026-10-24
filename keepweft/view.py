"""Fixed read-only ledger application endpoint. No arbitrary SQL or shell."""
import contextlib
import argparse,json,os,fcntl,signal,hmac
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
from .data import readonly,checkpoint
import time

READ_IDLE_SECONDS=.5

def main():
    p=argparse.ArgumentParser();p.add_argument('--database',type=Path,required=True);p.add_argument('--ready',type=Path,required=True);p.add_argument('--guard-fd',type=int);p.add_argument('--instance-id');p.add_argument('--nonce');p.add_argument('--barriers',type=Path);a=p.parse_args()
    if a.guard_fd is not None:
        os.fstat(a.guard_fd)
        fcntl.flock(a.guard_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    class Handler(BaseHTTPRequestHandler):
        # A silent local client must not monopolize the single reader before auth.
        # This is an inactivity limit, not a total deadline or DoS guarantee.
        timeout=READ_IDLE_SECONDS
        def do_GET(self):
            if a.guard_fd is not None and not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+a.nonce):self.send_error(403);return
            if self.path!='/summary':self.send_error(404);return
            try:
                with contextlib.closing(readonly(a.database)) as c:
                    c.set_progress_handler(lambda:0,1000)
                    identity=c.execute('select uuid from meta').fetchone()[0]
                    count,last=c.execute('select count(*),coalesce(max(seq),0) from tx').fetchone()
                value=dict(uuid=identity,count=count,max_seq=last)
                if a.guard_fd is not None:value.update(instance_id=a.instance_id,nonce=a.nonce)
                b=json.dumps(value).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
            except Exception:self.send_error(503)
        def log_message(self,*args):pass
    def stopping(signum,frame):raise SystemExit(0)
    signal.signal(signal.SIGTERM,stopping)
    server=HTTPServer(('127.0.0.1',0),Handler)
    checkpoint(a.barriers,'reader_before_ready',time.monotonic()+10)
    tmp=a.ready.with_suffix('.tmp')
    tmp.write_text(json.dumps(dict(port=server.server_port,nonce=a.nonce,pid=os.getpid())) if a.guard_fd is not None else str(server.server_port))
    os.replace(tmp,a.ready)
    server.serve_forever()
if __name__=='__main__':main()
