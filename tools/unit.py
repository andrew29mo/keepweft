import argparse,io,json,platform,sqlite3,unittest
from pathlib import Path
from .evidence import manifest,fingerprint
from keepweft.data import runtime

def main():
    if not __debug__:raise RuntimeError('Validation requires normal Python')
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    suite=unittest.defaultTestLoader.discover('tests')
    def ids(x):return [v for c in x for v in ids(c)] if isinstance(x,unittest.TestSuite) else [x.id()]
    names=ids(suite);stream=io.StringIO();r=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    value=dict(passed=r.wasSuccessful() and not r.skipped,count=r.testsRun,tests=names,failures=len(r.failures),errors=len(r.errors),skipped=len(r.skipped),source_sha256=fingerprint(manifest()),platform=platform.system(),runtime=runtime())
    a.output.write_text(json.dumps(value,indent=2)+'\n');print(stream.getvalue());raise SystemExit(0 if value['passed'] else 1)
if __name__=='__main__':main()
