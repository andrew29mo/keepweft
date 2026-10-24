import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from keepweft.core import Controller
from keepweft.data import Refused,init_ledger
from keepweft import reader
from tools.phase2_cases import CASES

class ServiceReaderCases(unittest.TestCase):pass
for name,fn in CASES:
    def test(self,fn=fn):
        with tempfile.TemporaryDirectory() as p:fn(Path(p)/'case')
    setattr(ServiceReaderCases,'test_'+name,test)

class ReaderFailures(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name).resolve();src=self.p/'source';uid=init_ledger(src,4)
        self.c=Controller(self.p/'store',src,uid);self.bid=self.c.backup()['id'];self.rid=self.c.restore(self.bid)['id']
    def tearDown(self):
        # Test cleanup of owned children occurs only after all assertions.
        for proc in self.c.readers.values():
            if proc.poll() is None:proc.kill()
            proc.wait(timeout=3)
        self.c.close();self.tmp.cleanup()
    def test_unlink_failure_keeps_pin_and_copy(self):
        with patch.object(reader.shutil,'rmtree',side_effect=OSError('injected unlink failure')):
            with self.assertRaises(OSError):self.c.release(self.rid)
        self.assertTrue((self.c.root/'restores'/self.rid/'db.sqlite').exists());self.assertEqual(self.c.status()['backups'][0]['pins'],1)
        self.c.close()
        with Controller(self.p/'store') as c:self.assertEqual(c.status()['backups'][0]['pins'],0)
    def test_missing_copy_still_requires_parent_sync_before_unpin(self):
        with patch.object(reader,'sync_dir',side_effect=OSError('injected fsync failure')):
            with self.assertRaises(OSError):self.c.release(self.rid)
        self.assertFalse((self.c.root/'restores'/self.rid).exists());self.assertEqual(self.c.status()['backups'][0]['pins'],1);self.c.close()
        with patch.object(reader,'sync_dir',side_effect=OSError('still failing')):
            with self.assertRaises(OSError):Controller(self.p/'store')
        with Controller(self.p/'store') as c:self.assertEqual(c.status()['backups'][0]['pins'],0)
    def test_exec_failure_preserves_pin_without_reader(self):
        with patch.object(reader.subprocess,'Popen',side_effect=OSError('exec failed')):
            with self.assertRaises(OSError):reader.start(self.c,self.rid,self.c.token)
        self.assertEqual(self.c.status()['backups'][0]['pins'],1)
        reader.stop(self.c,self.rid,self.c.token);self.c.release(self.rid)
    def test_full_receipts_and_capacity_do_not_block_stop_release(self):
        reader.start(self.c,self.rid,self.c.token)
        self.c.cfg['budget_bytes']=1;self.c.cfg['max_receipts']=1
        self.assertTrue(reader.stop(self.c,self.rid,self.c.token)['exit_proven']);self.c.release(self.rid)
        self.assertEqual(self.c.status()['backups'][0]['pins'],0)
    def test_guard_inode_never_replaced_on_release_restart(self):
        guard=reader.guard_path(self.c,self.rid);inode=guard.stat().st_ino;self.c.release(self.rid);self.c.close()
        with Controller(self.p/'store') as c:
            self.assertEqual(guard.stat().st_ino,inode)
            with self.assertRaises(Refused):c.release(self.rid)
    def test_mismatching_query_is_not_ready(self):
        with patch.object(reader,'query',side_effect=Refused('identity mismatch')):
            with self.assertRaises(Refused):reader.start(self.c,self.rid,self.c.token)
        self.assertEqual(self.c.status()['backups'][0]['pins'],1)
        self.assertTrue(reader.stop(self.c,self.rid,self.c.token)['exit_proven']);self.c.release(self.rid)

    def test_service_status_bounds_history_and_keeps_active_reference(self):
        from keepweft.service import Service,MAX_FRAME
        # Actual retained catalog rows, not a stubbed status response.
        manifest=self.c.db.execute('select manifest from backups where id=?',(self.bid,)).fetchone()[0]
        for n in range(100):
            ident=format(n,'032x')
            self.c.db.execute("insert into backups values(?,?,'DELETED',0)",(ident,manifest))
            self.c.db.execute("insert into restores values(?,?,'RELEASED',?)",(ident,self.bid,manifest))
        service=Service(self.c)
        try:
            value=service.answer(dict(action='status',args={}))
            inventory=value['inventory']
            self.assertLess(len(json.dumps(value).encode()),MAX_FRAME)
            self.assertTrue(inventory['history_truncated'])
            self.assertEqual(inventory['counts'],dict(backups=101,restores=101))
            self.assertIn(self.rid,[r['id'] for r in inventory['restores']])
            self.assertIn(self.bid,[r['id'] for r in inventory['backups']])
            self.assertEqual(inventory['token'],self.c.token)
        finally:service.close()

    def test_failed_deadline_kill_retains_unknown_reader_until_proven_exit(self):
        barrier=self.p/'barriers';barrier.mkdir();(barrier/'reader_before_ready.arm').touch();self.c.barriers=barrier
        with patch.object(reader.subprocess.Popen,'kill',return_value=None) as attempted:
            with self.assertRaises(TimeoutError):reader.start(self.c,self.rid,self.c.token,timeout=.5)
        attempted.assert_called_once()
        self.assertTrue((barrier/'reader_before_ready.seen').exists())
        proc=self.c.readers[self.rid];self.assertIsNone(proc.poll())
        with self.assertRaises(Refused):self.c.release(self.rid)
        self.assertTrue((self.c.root/'restores'/self.rid/'db.sqlite').exists())
        self.assertEqual(self.c.status()['backups'][0]['pins'],1)
        self.assertEqual(self.c.status()['restores'][0]['state'],'STOP_REQUESTED')
        self.assertTrue(reader.stop(self.c,self.rid,self.c.token)['exit_proven'])
        self.c.release(self.rid);self.assertEqual(self.c.status()['backups'][0]['pins'],0)
