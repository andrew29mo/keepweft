import hashlib,json
import keepweft
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def manifest():
    paths=[p for name in ('tools','tests') for p in (ROOT/name).rglob('*') if p.is_file() and p.suffix in ('.py','.json') and '__pycache__' not in p.parts]
    paths += [ROOT/'pyproject.toml']
    result={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    product=Path(keepweft.__file__).resolve().parent
    result.update({'keepweft/'+str(p.relative_to(product)):hashlib.sha256(p.read_bytes()).hexdigest() for p in product.rglob('*.py') if '__pycache__' not in p.parts})
    return dict(sorted(result.items()))
def fingerprint(files):return hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def require(test,message):
    if not test:raise ValueError(message)
