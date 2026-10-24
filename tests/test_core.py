import copy,json,os,sqlite3,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from keepweft.core import Controller,Busy,Degraded,usage
from keepweft.data import Refused,init_ledger,append,readonly,inspect,verify_closed
from tools.testing import owned_snapshot

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name).resolve();self.source=self.p/'live.sqlite';self.uid=init_ledger(self.source,12);self.root=self.p/'store'
    def tearDown(self):self.tmp.cleanup()
    def controller(self,**kw):return Controller(self.root,self.source,self.uid,**kw)
    def test_roundtrip_and_restart(self):
        with self.controller() as c:
            m=c.backup();r=c.restore(m['id']);self.assertEqual(r['expected'],m['expected']);self.assertEqual(m['expected']['count'],12)
        with self.controller() as c:
            self.assertEqual(c.status()['restores'][0]['state'],'READY');c.release(r['id'])
    def test_wrong_source_uuid_rejected(self):
        with Controller(self.root,self.source,'wrong') as c:
            with self.assertRaises(Refused):c.backup()
            self.assertEqual(c.status()['backups'],[])
    def test_missing_source_does_not_create(self):
        bad=self.p/'missing.sqlite'
        with self.assertRaises(Refused):Controller(self.root,bad,self.uid)
        self.assertFalse(bad.exists())
    def test_missing_catalog_never_reconstructs_inventory(self):
        with self.controller() as c:c.backup()
        (self.root/'catalog.sqlite').unlink()
        with self.assertRaises(Degraded):self.controller()
        self.assertTrue(any((self.root/'backups').iterdir()))
    def test_source_cannot_be_inside_store(self):
        root=self.p/'new';root.mkdir(mode=0o700);src=root/'source.sqlite';init_ledger(src)
        with self.assertRaises(Refused):Controller(root,src,self.uid)
    def test_second_writer_is_busy(self):
        with self.controller():
            with self.assertRaises(Busy):self.controller()
    def test_epoch_and_revision_independent(self):
        with self.controller() as c:
            t=c.token;c.backup()
            for q in (dict(epoch=t['epoch']-1,revision=c.token['revision']),dict(epoch=c.token['epoch'],revision=t['revision'])):
                before=owned_snapshot(c)
                with self.assertRaises(Refused):c.backup(q)
                self.assertEqual(before,owned_snapshot(c))
        with self.controller() as c:
            with self.assertRaises(Refused):c.backup(dict(epoch=t['epoch'],revision=c.token['revision']))
    def test_retention_and_latest_protection(self):
        with self.controller() as c:
            a=c.backup();b=c.backup()
            with self.assertRaises(Refused):c.delete(b['id'])
            d=c.backup();s=c.status()['backups'];self.assertEqual([x['state'] for x in s],['DELETED','AVAILABLE','AVAILABLE'])
            self.assertFalse((self.root/'backups'/a['id']).exists());self.assertNotEqual(b['id'],d['id'])
    def test_pin_blocks_deletion_and_rotation(self):
        with self.controller() as c:
            a=c.backup();r=c.restore(a['id']);b=c.backup()
            with self.assertRaises(Refused):c.delete(a['id'])
            with self.assertRaises(Refused):c.backup()
            c.release(r['id']);c.backup()
    def test_one_restored_instance(self):
        with self.controller() as c:
            a=c.backup();c.restore(a['id'])
            with self.assertRaises(Refused):c.restore(a['id'])
    def test_receipts_are_bounded_without_silent_eviction(self):
        with self.controller(options=dict(max_receipts=1)) as c:
            c.backup()
            with self.assertRaises(Refused):c.backup()
            self.assertEqual(len(c.status()['operations']),1)
    def test_soft_capacity_refusal_preserves_backup(self):
        with self.controller() as c:
            m=c.backup();before=c.status()['backups'];c.cfg['budget_bytes']=usage(self.root)['logical_bytes']+1
            with self.assertRaises(Refused):c.backup()
            self.assertEqual(before,c.status()['backups']);self.assertTrue((self.root/'backups'/m['id']/'db.sqlite').exists())
    def test_artifact_limit_rejects(self):
        with self.controller(options=dict(artifact_bytes=4096)) as c:
            with self.assertRaises(Refused):c.backup()
            self.assertEqual(c.status()['backups'],[])
    def test_cancellation_reaps_before_cleanup(self):
        cancel=self.p/'cancel';cancel.touch()
        with self.controller() as c:
            with self.assertRaises(InterruptedError):c.backup(cancel_path=cancel)
            self.assertEqual(list((self.root/'staging').iterdir()),[])
            self.assertEqual(c.status()['operations'][-1]['state'],'CANCELLED')
    def test_timeout_and_deadline_validation(self):
        barrier=self.p/'barrier';barrier.mkdir();(barrier/'snapshot_open.arm').touch()
        with self.controller(barriers=barrier) as c:
            for limit in (0,61):
                with self.assertRaises(Refused):c.backup(timeout=limit)
            with self.assertRaises((Refused,InterruptedError)):c.backup(timeout=.15)
            self.assertEqual(list((self.root/'staging').iterdir()),[])
    def test_valid_sqlite_wrong_content_is_not_verified(self):
        with self.controller() as c:
            m=c.backup();p=self.root/'backups'/m['id']
            db=sqlite3.connect(p/'db.sqlite');db.execute('delete from item');db.execute('delete from tx');db.commit();db.close()
            with self.assertRaises(Refused):c.restore(m['id'])
    def test_foreign_key_error_rejected(self):
        db=sqlite3.connect(self.source);db.execute('insert into item values(999,0)');db.commit();db.close()
        with self.controller() as c:
            with self.assertRaises(Refused):c.backup()
    def test_schema_change_rejected(self):
        db=sqlite3.connect(self.source);db.execute('pragma user_version=2');db.close()
        with self.controller() as c:
            with self.assertRaises(Refused):c.backup()
    def test_hash_and_manifest_mismatch_fail_closed(self):
        with self.controller() as c:
            m=c.backup();p=self.root/'backups'/m['id']/'manifest.json';v=json.loads(p.read_text());v['sha256']='0'*64;p.write_text(json.dumps(v))
            with self.assertRaises(Degraded):c.restore(m['id'])
        with self.assertRaises(Degraded):self.controller()
    def test_symlink_store_and_object_rejected(self):
        link=self.p/'link';link.symlink_to(self.root)
        with self.assertRaises(Refused):Controller(link,self.source,self.uid)
        with self.controller() as c:
            m=c.backup();target=self.root/'backups'/m['id']/'db.sqlite';target.unlink();target.symlink_to(self.source)
            with self.assertRaises(Refused):c.restore(m['id'])
    def test_unknown_inventory_is_retained_not_deleted(self):
        with self.controller():pass
        foreign=self.root/'staging'/'unknown';foreign.mkdir();(foreign/'keep').write_text('keep')
        with self.assertRaises(Degraded):self.controller()
        self.assertEqual((foreign/'keep').read_text(),'keep')
    def test_metadata_failure_prevents_worker_start(self):
        with self.controller() as c:
            with patch.object(c,'_phase',side_effect=sqlite3.OperationalError('disk full')),patch('keepweft.core.subprocess.Popen') as spawn:
                with self.assertRaises(sqlite3.Error):c.backup()
                spawn.assert_not_called()
            self.assertTrue(c.blocked)
    def test_ready_restore_missing_after_restart_is_not_ready(self):
        with self.controller() as c:
            m=c.backup();r=c.restore(m['id'])
        Path(r['path']).unlink()
        with self.assertRaises(Refused):self.controller()
    def test_pin_corruption_not_silently_repaired(self):
        with self.controller() as c:
            m=c.backup();c.db.execute('update backups set pins=1')
        with self.assertRaises(Degraded):self.controller()
    def test_validation_closes_read_connection_on_success_and_failure(self):
        from keepweft import data
        with self.controller() as c:
            m=c.backup();path=self.root/'backups'/m['id'];captured=[]
            def capture(p):
                db=readonly(p);captured.append(db);return db
            with patch.object(data,'readonly',side_effect=capture):
                verify_closed(path,m['expected'],c.cfg['artifact_bytes'],time.monotonic()+5)
                bad=copy.deepcopy(m['expected']);bad['uuid']='wrong'
                with self.assertRaises(Refused):verify_closed(path,bad,c.cfg['artifact_bytes'],time.monotonic()+5)
            self.assertEqual(len(captured),2)
            for db in captured:
                with self.assertRaises(sqlite3.ProgrammingError):db.execute('select 1')
    def test_metadata_error_retires_controller_before_new_mutation(self):
        with self.controller() as c:
            with self.assertRaises(sqlite3.Error):
                with c.tx():c.db.execute('insert into unknown_table values(1)')
            self.assertTrue(c.blocked)
            with self.assertRaises(Degraded):c.backup()
    def test_worker_error_pipe_survives_empty_durable_error_file(self):
        from keepweft.core import worker_error
        p=self.p/'stage';p.mkdir();(p/'error.json').write_text('')
        expected=dict(error='OperationalError: database or disk is full',sqlite_errorcode=13)
        self.assertEqual(worker_error(p,json.dumps(expected)),expected)
        self.assertIn('without a complete',worker_error(p,'')['error'])
    def test_normal_close_retains_real_worker_lifetime_lock(self):
        import subprocess,sys,uuid
        from keepweft.data import dump
        c=self.controller();ident=c._new('backup',dict(reserved=17*1024*1024))
        stage=self.root/'staging'/ident;stage.mkdir();b=self.p/'barriers';b.mkdir();(b/'copy_complete.arm').touch();(b/'process_exit.arm').touch()
        job=dict(source=str(self.source),expected_uuid=self.uid,stage=str(stage),deadline=time.monotonic()+5,max_bytes=8*1024*1024,wal_growth_limit=32*1024*1024,barriers=str(b),cancel_path=None,lock_fd=c.fd)
        dump(stage/'job.json',job)
        proc=subprocess.Popen([sys.executable,'-m','keepweft.worker',str(stage/'job.json')],pass_fds=(c.fd,),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            end=time.monotonic()+3
            while not (b/'copy_complete.seen').exists() and time.monotonic()<end:time.sleep(.01)
            self.assertTrue((b/'copy_complete.seen').exists());c.close()
            with self.assertRaises(Busy):self.controller()
            (b/'copy_complete.release').touch()
            end=time.monotonic()+3
            while not (b/'process_exit.seen').exists() and time.monotonic()<end:time.sleep(.01)
            self.assertTrue((b/'process_exit.seen').exists())
            with self.assertRaises(Busy):self.controller()
            (b/'process_exit.release').touch();self.assertEqual(proc.wait(timeout=3),0)
            with self.controller() as new:
                self.assertEqual(new.status()['backups'],[]);self.assertEqual(list((self.root/'staging').iterdir()),[])
        finally:
            c.close()
            if proc.poll() is None:proc.kill();proc.wait(timeout=3)
    def test_restored_copy_is_distinct_and_does_not_read_new_source(self):
        with self.controller() as c:
            m=c.backup();db=sqlite3.connect(self.source,isolation_level=None);append(db,13);db.close();r=c.restore(m['id'])
            self.assertEqual(Path(r['path']),self.root/'restores'/r['id']/'db.sqlite')
            self.assertNotEqual(Path(r['path']).stat().st_ino,self.source.stat().st_ino)
            import contextlib
            with contextlib.closing(readonly(r['path'])) as restored:self.assertEqual(restored.execute('select count(*) from tx').fetchone()[0],12)
            with contextlib.closing(readonly(self.source)) as source:self.assertEqual(source.execute('select count(*) from tx').fetchone()[0],13)
    def test_rollback_failure_still_retires_and_preserves_original_error(self):
        with self.controller() as c:
            c.db.set_authorizer(lambda action,arg,*rest:sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_TRANSACTION and arg=='ROLLBACK' else sqlite3.SQLITE_OK)
            with self.assertRaisesRegex(sqlite3.OperationalError,'unknown_table'):
                with c.tx():c.db.execute('insert into unknown_table values(1)')
            self.assertTrue(c.blocked)
            with self.assertRaises(Degraded):c.backup()
            c.db.set_authorizer(None);c.db.rollback()

    def test_null_transaction_item_parent_refuses_formal_backup(self):
        with sqlite3.connect(self.source) as db:
            db.execute('update item set seq=NULL where seq=1')
            self.assertEqual(db.execute('pragma foreign_key_check').fetchall(),[])
        with self.controller() as c:
            with self.assertRaisesRegex(Refused,'Transaction item parent mismatch'):c.backup()
            self.assertEqual(c.status()['backups'],[])
            self.assertFalse(any((self.root/'staging').iterdir()))

    def test_missing_fk_orphan_item_refuses_formal_backup(self):
        with sqlite3.connect(self.source) as db:
            db.execute('drop table item')
            db.execute('create table item(seq integer,part integer,primary key(seq,part))')
            db.executemany('insert into item values(?,?)',[(1000+seq,part) for seq in range(1,13) for part in (0,1)])
            self.assertEqual(db.execute('pragma foreign_key_check').fetchall(),[])
        with self.controller() as c:
            with self.assertRaisesRegex(Refused,'Transaction item parent mismatch'):c.backup()
            self.assertEqual(c.status()['backups'],[])
            self.assertFalse(any((self.root/'staging').iterdir()))
