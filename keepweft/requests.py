"""Durable phase-one backup requests; all calls belong to the controller thread."""
import hashlib
import json
import math
import re
import uuid
from .data import Refused

TERMINAL = ('AVAILABLE','FAILED','CANCELLED','INTERRUPTED')

class ProtocolError(Refused):
    def __init__(self, code, message):
        super().__init__(message);self.code=code

def valid_int(x):return type(x) is int and 0 <= x < 2**63

class Requests:
    def __init__(self, controller, queue_limit=16):
        self.c=controller;self.db=controller.db;self.queue_limit=queue_limit
        if type(queue_limit) is not int or not 1 <= queue_limit <= 16:raise Refused('Invalid queue limit')
        with self.c.tx():
            self.db.execute('create table if not exists request_namespace(id integer primary key, generation integer not null)')
            self.db.execute('insert or ignore into request_namespace values(1,1)')
            self.db.execute('''create table if not exists requests(epoch integer, generation integer,
                request_id text, digest text not null, payload text not null, operation_id text unique not null,
                cancel_requested integer not null default 0, primary key(epoch,generation,request_id))''')
        # Controller.recover already reconciled all known prior-epoch operations.
        # No new old-epoch submission can ever execute, even after receipt GC.
        with self.c.tx():
            self.db.execute("update ops set state='CANCELLED' where state='FAILED' and id in (select operation_id from requests where cancel_requested=1)")
            self.db.execute('delete from requests where generation < ?', (self.generation-1,))
            self._gc_ops()
        self.active=None
        self.rotating=False

    @property
    def generation(self):return self.db.execute('select generation from request_namespace where id=1').fetchone()[0]
    @property
    def namespace(self):return dict(epoch=self.c.token['epoch'],generation=self.generation)

    def _key(self, env):
        if not isinstance(env,dict) or set(env) != {'epoch','generation','request_id','command'}:
            raise ProtocolError('INVALID','Exact request envelope required')
        if not valid_int(env['epoch']) or not valid_int(env['generation']) or not isinstance(env['request_id'],str) or not re.fullmatch('[0-9a-f]{32}',env['request_id']):
            raise ProtocolError('INVALID','Invalid request identity')
        return env['epoch'],env['generation'],env['request_id']

    def _payload(self, command):
        if not isinstance(command,dict) or set(command) != {'kind','timeout'} or command['kind']!='backup':
            raise ProtocolError('INVALID','Phase one supports backup only with explicit timeout')
        t=command['timeout']
        if type(t) not in (float,int) or not math.isfinite(t) or not 0 < t <= 60:
            raise ProtocolError('INVALID','Timeout must be finite and in (0,60]')
        text=json.dumps(dict(kind='backup',timeout=float(t)),sort_keys=True,separators=(',',':'),allow_nan=False)
        return text,hashlib.sha256(text.encode()).hexdigest()

    def lookup(self, epoch, generation, request_id):
        if not valid_int(epoch) or not valid_int(generation) or not isinstance(request_id,str) or not re.fullmatch('[0-9a-f]{32}',request_id):
            raise ProtocolError('INVALID','Invalid lookup key')
        row=self.db.execute('''select r.operation_id,r.digest,r.cancel_requested,o.state,o.details
            from requests r join ops o on r.operation_id=o.id where r.epoch=? and r.generation=? and r.request_id=?''',(epoch,generation,request_id)).fetchone()
        if row is None:
            ns=self.namespace
            code='RESULT_GONE' if epoch<ns['epoch'] or generation<ns['generation'] else 'NOT_FOUND'
            raise ProtocolError(code,'No retained result; this is not permission to resubmit under new identity')
        ident,digest,cancel,state,details=row;d=json.loads(details)
        deleted=set(d.get('retention_deleted',[]))
        for bid in d.get('retention_planned',[]):
            r=self.db.execute('select state from backups where id=?',(bid,)).fetchone()
            if r and r[0]=='DELETED':deleted.add(bid)
        return dict(operation_id=ident,digest=digest,state='CANCEL_REQUESTED' if cancel and state not in TERMINAL and state not in ('PUBLISHING','CLEANUP_PENDING') else state,
                    cancel_requested=bool(cancel),retention_deleted=sorted(deleted),
                    error=d.get('error',d.get('reason')),result_id=ident if state=='AVAILABLE' else None,
                    reserved=d.get('reserved',0))

    def submit(self, env):
        key=self._key(env);payload,digest=self._payload(env['command'])
        old=self.db.execute('select digest from requests where epoch=? and generation=? and request_id=?',key).fetchone()
        if old:
            if old[0]!=digest:raise ProtocolError('CONFLICT','Request identity is bound to another command')
            return self.lookup(*key)
        if (key[0],key[1]) != (self.namespace['epoch'],self.generation):
            raise ProtocolError('RETIRED','Only the current epoch and generation admit new requests')
        self.c._check(None)
        count=self.db.execute('select count(*) from requests where generation=?',(self.generation,)).fetchone()[0]
        if count>=self.c.cfg['max_receipts']:raise ProtocolError('RECEIPT_FULL','Rotate only after all work is reconciled')
        queued=self.db.execute("select count(*) from ops where state='QUEUED'").fetchone()[0]
        if queued>=self.queue_limit:raise ProtocolError('QUEUE_FULL','No request accepted')
        # No retention before predictable storage refusal; dispatch rechecks too.
        self.c._reserve()
        ident=uuid.uuid4().hex
        with self.c.tx():
            self.db.execute("insert into ops values(?,?,?,'QUEUED',?)",(ident,key[0],'backup',json.dumps(dict(reserved=0))))
            self.db.execute('insert into requests values(?,?,?,?,?,?,0)',(*key,digest,payload,ident))
            self.c._revision()
        return self.lookup(*key)

    def rotate(self, epoch, generation):
        if not valid_int(epoch) or not valid_int(generation) or dict(epoch=epoch,generation=generation)!=self.namespace:
            raise ProtocolError('RETIRED','Namespace changed')
        self.c._check(None)
        if self.rotating:raise ProtocolError('BUSY','Generation retirement in progress')
        if self.active or self.db.execute("select 1 from ops where state not in ('AVAILABLE','READY','FAILED','CANCELLED','INTERRUPTED') limit 1").fetchone():
            raise ProtocolError('BUSY','Nonterminal operations prevent generation retirement')
        if any((self.c.root/'staging').iterdir()):raise ProtocolError('BUSY','Unknown staging occupancy')
        g=self.generation
        if g>=2**63-1:raise ProtocolError('CAPACITY','Namespace exhausted')
        # Atomic namespace advance before GC. At most current + one retired generation.
        with self.c.tx():
            self.db.execute('update request_namespace set generation=? where id=1',(g+1,))
        self.rotating=True
        try:
            self.c._barrier('generation_advanced',__import__('time').monotonic()+60)
            with self.c.tx():
                self.db.execute('delete from requests where generation < ?',(g,))
                self._gc_ops()
        finally:self.rotating=False
        return self.namespace

    def _gc_ops(self):
        # Artifact catalog rows survive request expiry; old object IDs never become paths
        # supplied by the request API. Artifact/guard GC is a later milestone.
        self.db.execute("delete from ops where state in ('AVAILABLE','FAILED','CANCELLED','INTERRUPTED') and id not in (select operation_id from requests) and id not in (select id from restores)")

    def cancel(self, env):
        key=self._key(env);_,digest=self._payload(env['command'])
        r=self.lookup(*key)
        if r['digest']!=digest:raise ProtocolError('CONFLICT','Payload differs')
        self.c._check(None)
        # New authority is required for mutation. Exact old results remain queryable.
        if key[0]!=self.namespace['epoch']:raise ProtocolError('RETIRED','Cannot mutate a prior epoch')
        state=self.db.execute('select state from ops where id=?',(r['operation_id'],)).fetchone()[0]
        if state in ('PUBLISHING','AVAILABLE'):return dict(outcome='TOO_LATE',receipt=r)
        if state in TERMINAL:return dict(outcome=state,receipt=r)
        with self.c.tx():
            self.db.execute('update requests set cancel_requested=1 where epoch=? and generation=? and request_id=?',key)
            if state=='QUEUED':self.db.execute("update ops set state='CANCELLED' where id=?",(r['operation_id'],))
            self.c._revision()
        return dict(outcome='CANCELLED' if state=='QUEUED' else 'CANCEL_ACCEPTED',receipt=self.lookup(*key))

    def is_cancelled(self):
        return bool(self.active and self.db.execute('select cancel_requested from requests where operation_id=?',(self.active,)).fetchone()[0])

    def dispatch(self):
        if self.c.blocked:return
        row=self.db.execute("select o.id,r.payload from ops o join requests r on r.operation_id=o.id where o.state='QUEUED' order by o.rowid limit 1").fetchone()
        if not row:return
        self.active=row[0];self.c.cancelled=self.is_cancelled
        try:self.c.backup(timeout=json.loads(row[1])['timeout'],operation_id=row[0])
        except Exception:
            # A programming/storage failure outside the backup cleanup boundary
            # must not create an automatic retry loop or fake terminal success.
            state=self.db.execute('select state from ops where id=?',(row[0],)).fetchone()
            if state is None or state[0] not in TERMINAL:self.c.blocked=True
        finally:self.c.cancelled=lambda:False;self.active=None

    def summary(self):
        rows=self.db.execute('select state,count(*) from ops group by state').fetchall()
        return dict(namespace=self.namespace,blocked=self.c.blocked,active=self.active,states=dict(rows),
                    receipts=self.db.execute('select count(*) from requests').fetchone()[0],
                    current_receipts=self.db.execute('select count(*) from requests where generation=?',(self.generation,)).fetchone()[0])
