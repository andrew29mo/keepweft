"""Phase-one local backup control service; no scheduler or managed reader yet."""
import argparse
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import stat
import time
from .core import Controller
from .data import Refused, dump
from .requests import Requests, ProtocolError

MAX_FRAME=65536
MAX_CLIENTS=8

class Service:
    def __init__(self, controller, queue_limit=16):
        self.c=controller;self.requests=Requests(controller,queue_limit)
        self.path=controller.root/'control.sock';self.stop=False
        self.selector=selectors.DefaultSelector();self.clients={}
        if self.path.exists() or self.path.is_symlink():
            st=self.path.lstat()
            if not stat.S_ISSOCK(st.st_mode) or st.st_uid!=os.getuid():raise Refused('Unsafe socket path')
            self.path.unlink()
        self.listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            self.listener.bind(str(self.path));self.path.chmod(0o600)
            self.listener.listen(MAX_CLIENTS);self.listener.setblocking(False)
            self.selector.register(self.listener,selectors.EVENT_READ)
        except BaseException:
            self.listener.close();self.selector.close();raise
        self.c.progress=self.pump

    def answer(self, message):
        if not isinstance(message,dict) or set(message)!={'action','args'} or not isinstance(message['args'],dict):
            raise ProtocolError('INVALID','Exact action/args object required')
        action=message['action'];args=message['args']
        if self.stop and action in ('submit','rotate'):raise ProtocolError('STOPPING','Admission closed')
        if action=='status' and not args:return self.requests.summary()
        if action=='submit':return self.requests.submit(args)
        if action=='cancel':return self.requests.cancel(args)
        if action=='lookup' and set(args)=={'epoch','generation','request_id'}:return self.requests.lookup(**args)
        if action=='rotate' and set(args)=={'epoch','generation'}:return self.requests.rotate(**args)
        raise ProtocolError('INVALID','Unsupported action/arguments')

    def drop(self, client):
        try:self.selector.unregister(client)
        except KeyError:pass
        self.clients.pop(client,None);client.close()

    def pump(self, timeout=0):
        # Every turn is bounded by clients/frame size; no socket has a blocking read.
        now=time.monotonic()
        for client,state in list(self.clients.items()):
            if now-state['start']>2:self.drop(client)
        for key,events in self.selector.select(timeout):
            if key.fileobj is self.listener:
                try:client,_=self.listener.accept()
                except BlockingIOError:continue
                if len(self.clients)>=MAX_CLIENTS:client.close();continue
                client.setblocking(False)
                self.clients[client]=dict(start=now,buf=b'',out=b'')
                self.selector.register(client,selectors.EVENT_READ);continue
            client=key.fileobj;state=self.clients.get(client)
            if state is None:continue
            try:
                if events & selectors.EVENT_WRITE:
                    sent=client.send(state['out']);state['out']=state['out'][sent:]
                    if not state['out']:self.drop(client)
                else:
                    data=client.recv(8192)
                    if not data:self.drop(client);continue
                    state['buf']+=data
                    if len(state['buf'])>MAX_FRAME:self.drop(client);continue
                    if b'\n' not in state['buf']:continue
                    raw,tail=state['buf'].split(b'\n',1)
                    try:
                        if tail:raise ProtocolError('INVALID','One frame per connection')
                        def pairs(items):
                            d={}
                            for k,v in items:
                                if k in d:raise ValueError('Duplicate JSON key')
                                d[k]=v
                            return d
                        msg=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
                        result=self.answer(msg);reply=dict(ok=True,result=result)
                    except Exception as exc:
                        reply=dict(ok=False,code=getattr(exc,'code',type(exc).__name__),detail=str(exc))
                    state['out']=(json.dumps(reply,allow_nan=False)+'\n').encode()
                    self.selector.modify(client,selectors.EVENT_WRITE)
            except (ConnectionError,OSError):self.drop(client)
        if self.stop and self.requests.active:
            # Graceful stop requests cancellation only before durable publication.
            row=self.c.db.execute('select state from ops where id=?',(self.requests.active,)).fetchone()
            if row and row[0] not in ('PUBLISHING','AVAILABLE') and not self.c.blocked:
                with self.c.tx():self.c.db.execute('update requests set cancel_requested=1 where operation_id=?',(self.requests.active,))

    def run(self):
        while not self.stop:
            self.pump(.01)
            if not self.stop:self.requests.dispatch()

    def close(self):
        self.c.progress=lambda:None
        for client in list(self.clients):self.drop(client)
        self.selector.close();self.listener.close();self.path.unlink(missing_ok=True)


def call(root, action, args, timeout=5):
    payload=(json.dumps(dict(action=action,args=args),allow_nan=False)+'\n').encode()
    if len(payload)>MAX_FRAME:raise Refused('Request frame too large')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
        s.settimeout(timeout);s.connect(str(Path(root)/'control.sock'));s.sendall(payload)
        data=b''
        while b'\n' not in data:
            chunk=s.recv(8192)
            if not chunk:raise ConnectionError('Response lost; retry the same saved envelope')
            data+=chunk
            if len(data)>MAX_FRAME:raise Refused('Oversized response')
        return json.loads(data)


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--source',type=Path);p.add_argument('--uuid');p.add_argument('--options',type=Path);p.add_argument('--barriers',type=Path);p.add_argument('--queue-limit',type=int,default=16)
    a=p.parse_args()
    with Controller(a.root,a.source,a.uuid,json.loads(a.options.read_text()) if a.options else None,a.barriers) as c:
        service=Service(c,a.queue_limit)
        def stop(signum,frame):service.stop=True
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        try:service.run()
        finally:service.close()
if __name__=='__main__':main()
