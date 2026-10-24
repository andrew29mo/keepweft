import copy
from pathlib import Path
import tempfile
import unittest
from tools.closeout_cases import documented,capacity,validate_samples,CYCLES

class CloseoutCases(unittest.TestCase):
    def test_documented_cli(self):
        with tempfile.TemporaryDirectory() as p:documented(Path(p)/'case')
    def test_receipt_exhaustion_preserves_stop_release(self):
        with tempfile.TemporaryDirectory() as p:capacity(Path(p)/'case','receipts')
    def test_byte_exhaustion_preserves_stop_release(self):
        with tempfile.TemporaryDirectory() as p:capacity(Path(p)/'case','logical_bytes')
    def test_resource_checks_reject_restart_leaks_and_missing_observation(self):
        samples=[dict(cycle=n,pid=42,rss_kib=20000,fds=8,fd_quiescent=True,fd_observations=[dict(seconds=t,fds=8,non_listener_sockets=0,targets={str(i):'fixture-file' for i in range(8)},unix_socket_flags={}) for t in (0,.01)],children=0,active_restores=0,pins=0,rows=dict(ops=2*n,requests=n,backups=n,restores=n,readers=0),guards=2*n,files=2+2*n,catalog_bytes=65536,logical_bytes=100000,allocated_bytes=131072,log_bytes=0) for n in range(CYCLES+1)]
        self.assertTrue(validate_samples(samples))
        for key,value in [('pid',43),('fds',9),('children',1),('pins',1),('rss_kib',25000),('guards',0),('log_bytes',100),('pid',-1),('fds',-1),('rss_kib',0),('rss_kib',float('nan')),('rss_kib',True),('logical_bytes',-1),('catalog_bytes',-1),('fd_quiescent',False)]:
            bad=copy.deepcopy(samples);bad[-1][key]=value
            with self.assertRaises(ValueError,msg=key):validate_samples(bad)
        with self.assertRaises(ValueError):validate_samples(samples[:-1])
        bad=copy.deepcopy(samples);bad[-1]['fd_observations'][-1]['non_listener_sockets']=1
        with self.assertRaises(ValueError):validate_samples(bad)
        transient=copy.deepcopy(samples)
        transient[-1]['fd_observations']=[dict(seconds=0,fds=9,non_listener_sockets=1,targets={**{str(i):'fixture-file' for i in range(8)},'8':'socket:[100]'},unix_socket_flags={'100':0}),*[dict(seconds=t,fds=8,non_listener_sockets=0,targets={str(i):'fixture-file' for i in range(8)},unix_socket_flags={}) for t in (.01,.02)]]
        self.assertTrue(validate_samples(transient))
        leaked=copy.deepcopy(samples);leaked[-1]['fds']=9
        for o in leaked[-1]['fd_observations']:o['fds']=9;o['targets']['8']='fixture-file'
        with self.assertRaises(ValueError):validate_samples(leaked)

    def test_owned_snapshot_ignores_only_shared_free_space(self):
        from unittest.mock import patch
        from keepweft.core import Controller,usage
        from keepweft.data import init_ledger
        from tools.testing import owned_snapshot
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp).resolve();src=p/'source';uid=init_ledger(src,4)
            with Controller(p/'store',src,uid) as c:
                before=owned_snapshot(c);u=usage(c.root)
                with patch('keepweft.core.usage',return_value=dict(u,filesystem_free_bytes=u['filesystem_free_bytes']+4096)):
                    self.assertEqual(before,owned_snapshot(c))
                # A real managed-file change still alters the witness, even with
                # the same patched accounting values. The observer checks bytes.
                (c.root/'unexpected').write_bytes(b'changed')
                with patch('keepweft.core.usage',return_value=u):
                    self.assertNotEqual(before,owned_snapshot(c))

    def test_capacity_observer_detects_manifest_catalog_and_receipt_mutation(self):
        from unittest.mock import patch
        import sqlite3
        from tools import closeout_cases as cases
        actual=cases.call
        for mode in ('receipts','logical_bytes'):
            for corrupt in ('manifest','catalog','receipt'):
                with self.subTest(mode=mode,corrupt=corrupt),tempfile.TemporaryDirectory() as tmp:
                    def mutate(root,action,args,**kw):
                        reply=actual(root,action,args,**kw)
                        if action=='submit' and reply.get('ok') is False:
                            if corrupt=='manifest':
                                for p in (Path(root)/'backups').glob('*/manifest.json'):p.write_text('{}')
                            else:
                                with sqlite3.connect(Path(root)/'catalog.sqlite') as db:
                                    db.execute("update backups set state='DELETED'" if corrupt=='catalog' else "update requests set digest='corrupted'")
                        return reply
                    with patch.object(cases,'call',side_effect=mutate):
                        with self.assertRaisesRegex(ValueError,'Refusal changed owned'):
                            cases.capacity(Path(tmp).resolve()/'case',mode)

    def test_vm_socket_path_preflight_no_side_effects(self):
        from tools.closeout_validate import check_socket_path
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'not-created'
            check_socket_path('/private/tmp/kw','keepweft-exp-ok')
            with self.assertRaisesRegex(ValueError,'socket path too long'):
                check_socket_path(root,'keepweft-exp-'+('x'*100))
            self.assertFalse(root.exists())
