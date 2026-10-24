import json
from pathlib import Path
import tempfile
import unittest
import uuid
from keepweft.core import Controller
from keepweft.data import init_ledger,Refused
from keepweft.requests import Requests,ProtocolError
from tools import phase1_cases

class RequestTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name).resolve();self.source=self.p/'live.sqlite';self.uid=init_ledger(self.source,12)
        self.c=Controller(self.p/'store',self.source,self.uid,dict(max_receipts=2));self.r=Requests(self.c,queue_limit=1)
    def tearDown(self):self.c.close();self.tmp.cleanup()
    def env(self):return dict(**self.r.namespace,request_id=uuid.uuid4().hex,command=dict(kind='backup',timeout=10))
    def test_payload_conflict_has_no_side_effect(self):
        e=self.env();a=self.r.submit(e);before=self.c.status()
        with self.assertRaises(ProtocolError):self.r.submit(dict(e,command=dict(kind='backup',timeout=9)))
        self.assertEqual(before,self.c.status());self.assertEqual(a,self.r.submit(e))
    def test_queue_full_does_not_create_receipt(self):
        self.r.submit(self.env());before=self.c.status()
        with self.assertRaises(ProtocolError):self.r.submit(self.env())
        self.assertEqual(before,self.c.status());self.assertEqual(self.r.summary()['receipts'],1)
    def test_queued_cancel_needs_no_slot(self):
        e=self.env();self.r.submit(e);self.assertEqual(self.r.cancel(e)['outcome'],'CANCELLED');self.assertEqual(self.r.cancel(e)['outcome'],'CANCELLED')
    def test_generation_cannot_retire_queued_work(self):
        self.r.submit(self.env())
        with self.assertRaises(ProtocolError):self.r.rotate(**self.r.namespace)
    def test_queued_work_does_not_recheck_global_revision(self):
        self.r.queue_limit=2;a=self.env();b=self.env();self.r.submit(a);self.r.submit(b);self.r.dispatch();self.r.dispatch()
        self.assertEqual(self.r.lookup(a['epoch'],a['generation'],a['request_id'])['state'],'AVAILABLE')
        self.assertEqual(self.r.lookup(b['epoch'],b['generation'],b['request_id'])['state'],'AVAILABLE')
    def test_nonfinite_boolean_and_unknown_commands_refused(self):
        for t in (True,float('nan'),float('inf'),0,61):
            with self.assertRaises(ProtocolError):self.r.submit(dict(self.env(),command=dict(kind='backup',timeout=t)))
        with self.assertRaises(ProtocolError):self.r.submit(dict(self.env(),command=dict(kind='delete',timeout=1)))
        self.assertEqual(self.r.summary()['receipts'],0)
    def test_dispatch_capacity_failure_terminalizes_without_prune(self):
        e=self.env();self.r.submit(e);self.c.cfg['budget_bytes']=1;self.r.dispatch()
        self.assertEqual(self.r.lookup(e['epoch'],e['generation'],e['request_id'])['state'],'FAILED')
    def test_unexpected_dispatch_failure_blocks_instead_of_replaying(self):
        from unittest.mock import patch
        e=self.env();self.r.submit(e)
        with patch.object(self.c,'backup',side_effect=RuntimeError('injected pre-cleanup fault')) as backup:
            self.r.dispatch();self.r.dispatch();self.assertEqual(backup.call_count,1)
        self.assertTrue(self.c.blocked)
        self.assertEqual(self.r.lookup(e['epoch'],e['generation'],e['request_id'])['state'],'QUEUED')
    def test_catalog_error_prevents_admission(self):
        import sqlite3
        from unittest.mock import patch
        self.c.db.execute('pragma max_page_count=1')
        # Actual SQLite page limit behavior is platform-dependent at current size;
        # use the formal transaction authorizer failure for deterministic retirement.
        self.c.db.set_authorizer(lambda action,*args:sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_INSERT else sqlite3.SQLITE_OK)
        with self.assertRaises(sqlite3.Error):self.r.submit(self.env())
        self.c.db.set_authorizer(None);self.assertTrue(self.c.blocked)
        with self.assertRaises(Refused):self.r.submit(self.env())

class ServiceCases(unittest.TestCase):
    pass

def add(name,fn):
    def test(self):
        with tempfile.TemporaryDirectory() as tmp:fn(Path(tmp).resolve()/'case')
    setattr(ServiceCases,'test_'+name,test)
for name,fn in phase1_cases.CASES:add(name,fn)

class ClientTests(unittest.TestCase):
    def test_prepare_is_durable_and_never_overwrites_retry_identity(self):
        import subprocess,sys
        from tools.phase1_cases import harness
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp).resolve()
            with harness(p/'case') as h:
                file=p/'envelope.json'
                args=[sys.executable,'-m','keepweft.client','prepare','--root',str(h.root),'--envelope',str(file)]
                a=subprocess.run(args,capture_output=True,text=True,timeout=5)
                self.assertEqual(a.returncode,0,a.stderr);before=file.read_bytes()
                b=subprocess.run(args,capture_output=True,text=True,timeout=5)
                self.assertNotEqual(b.returncode,0);self.assertEqual(file.read_bytes(),before)
                self.assertEqual(h.ok('status',{})['receipts'],0)

class RecoveryTests(unittest.TestCase):
    def test_queued_restart_is_interrupted_not_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp).resolve();source=p/'live.sqlite';uid=init_ledger(source,12);root=p/'store'
            with Controller(root,source,uid) as c:
                r=Requests(c);env=dict(**r.namespace,request_id=uuid.uuid4().hex,command=dict(kind='backup',timeout=10));r.submit(env)
            with Controller(root) as c:
                r=Requests(c);a=r.submit(env);self.assertEqual(a['state'],'INTERRUPTED');self.assertEqual(c.status()['backups'],[])
    def test_retention_side_effect_is_reported_even_when_new_backup_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp).resolve();source=p/'live.sqlite';uid=init_ledger(source,12)
            with Controller(p/'store',source,uid) as c:
                r=Requests(c)
                def env():return dict(**r.namespace,request_id=uuid.uuid4().hex,command=dict(kind='backup',timeout=10))
                a=env();r.submit(a);r.dispatch();b=env();r.submit(b);r.dispatch()
                import sqlite3
                db=sqlite3.connect(source);db.execute('pragma user_version=2');db.close()
                x=env();r.submit(x);r.dispatch();res=r.lookup(x['epoch'],x['generation'],x['request_id'])
                self.assertEqual(res['state'],'FAILED');self.assertEqual(res['retention_deleted'],[r.lookup(a['epoch'],a['generation'],a['request_id'])['operation_id']])
                self.assertEqual(len([v for v in c.status()['backups'] if v['state']=='AVAILABLE']),1)

class HarnessCleanupTests(unittest.TestCase):
    def test_stopped_service_timeout_kills_child_and_is_not_success(self):
        import signal,subprocess
        with tempfile.TemporaryDirectory() as tmp:
            h=phase1_cases.Harness(Path(tmp).resolve()/'case');h.start()
            h.proc.send_signal(signal.SIGSTOP)
            with self.assertRaises(subprocess.TimeoutExpired):h.close()
            self.assertIsNotNone(h.proc.poll());self.assertIsNone(h.log)
            with Controller(h.root) as c:self.assertFalse(c.blocked)

class RetentionFailureTests(unittest.TestCase):
    def exercise(self, fsync_failure):
        import errno
        from unittest.mock import patch
        from keepweft import core
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp).resolve();src=p/'live.sqlite';uid=init_ledger(src,12);root=p/'store'
            with Controller(root,src,uid) as c:
                a=c.backup()['id'];b=c.backup()['id'];r=Requests(c)
                env=dict(**r.namespace,request_id=uuid.uuid4().hex,command=dict(kind='backup',timeout=10));r.submit(env)
                real_sync=core.sync_dir;real_remove=core.shutil.rmtree
                def fail_sync(path):
                    if Path(path)==root/'backups':raise OSError(errno.EIO,'injected directory sync failure')
                    return real_sync(path)
                def fail_remove(path,*args,**kwargs):
                    if Path(path)==root/'backups'/a:raise PermissionError(errno.EACCES,'injected unlink refusal')
                    return real_remove(path,*args,**kwargs)
                with patch('keepweft.core.sync_dir',side_effect=fail_sync) if fsync_failure else patch('keepweft.core.shutil.rmtree',side_effect=fail_remove):r.dispatch()
                receipt=r.lookup(env['epoch'],env['generation'],env['request_id'])
                self.assertEqual(receipt['state'],'FAILED');self.assertEqual(receipt['retention_deleted'],[])
                self.assertEqual(receipt['retention_pending'],[a]);self.assertTrue(c.blocked)
                self.assertEqual((root/'backups'/a/'db.sqlite').exists(),not fsync_failure)
                self.assertTrue((root/'backups'/b/'db.sqlite').exists())
            if fsync_failure:
                # Even if the files are absent, recovery must sync the parent before
                # committing DELETED. A repeated sync error must refuse startup.
                with patch('keepweft.core.sync_dir',side_effect=fail_sync):
                    with self.assertRaises(OSError):Controller(root)
            calls=[]
            def observe(path):calls.append(Path(path));return real_sync(path)
            with patch('keepweft.core.sync_dir',side_effect=observe):
                with Controller(root) as c:
                    r=Requests(c);receipt=r.lookup(env['epoch'],env['generation'],env['request_id'])
                    self.assertEqual(receipt['retention_deleted'],[a]);self.assertEqual(receipt['retention_pending'],[])
                    self.assertIn(root/'backups',calls)
    def test_unlink_refusal_is_pending_not_completed_deletion(self):self.exercise(False)
    def test_parent_fsync_failure_remains_pending_until_recovery_sync(self):self.exercise(True)
