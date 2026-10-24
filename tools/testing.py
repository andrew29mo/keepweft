"""Test-only owned-state witness; unrelated host free space is not a mutation."""
from .evidence import require
from keepweft.data import digest_file

def owned_snapshot(controller):
    value=controller.status()
    # statvfs free bytes belongs to the whole shared filesystem, not this store.
    free=value['usage'].pop('filesystem_free_bytes')
    require(type(free) is int and free>=0,'Invalid free-space observation')
    files={str(p.relative_to(controller.root)):('directory' if p.is_dir() else digest_file(p)) for p in controller.root.rglob('*')}
    return dict(status=value,files=files)
