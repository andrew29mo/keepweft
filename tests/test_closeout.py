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
        samples=[dict(cycle=n,pid=42,rss_kib=20000,fds=8,children=0,active_restores=0,pins=0,rows=dict(ops=2*n,requests=n,backups=n,restores=n,readers=0),guards=2*n,catalog_bytes=65536,logical_bytes=100000,log_bytes=0) for n in range(CYCLES+1)]
        self.assertTrue(validate_samples(samples))
        for key,value in [('pid',43),('fds',9),('children',1),('pins',1),('rss_kib',25000),('guards',0),('log_bytes',100)]:
            bad=copy.deepcopy(samples);bad[-1][key]=value
            with self.assertRaises(ValueError,msg=key):validate_samples(bad)
        with self.assertRaises(ValueError):validate_samples(samples[:-1])

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
