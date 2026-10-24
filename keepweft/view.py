"""Fixed read-only ledger application endpoint. No arbitrary SQL or shell."""
import contextlib
import argparse,json
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
from .data import readonly

def main():
    p=argparse.ArgumentParser();p.add_argument('--database',type=Path,required=True);p.add_argument('--ready',type=Path,required=True);a=p.parse_args()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path!='/summary':self.send_error(404);return
            try:
                with contextlib.closing(readonly(a.database)) as c:
                    c.set_progress_handler(lambda:0,1000)
                    identity=c.execute('select uuid from meta').fetchone()[0]
                    count,last=c.execute('select count(*),coalesce(max(seq),0) from tx').fetchone()
                b=json.dumps(dict(uuid=identity,count=count,max_seq=last)).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
            except Exception:self.send_error(503)
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',0),Handler)
    a.ready.write_text(str(server.server_port))
    server.serve_forever()
if __name__=='__main__':main()
