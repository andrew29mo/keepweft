# MVP acceptance: exploration gates versus remaining delivery

Four technical explorations are prerequisites, not a claim that the full MVP is
finished. Actual receipts must name the installed core, source fingerprint,
SQLite runtime, faults and limits. No stage may silently skip or turn timeout
into success. Mac portable tests and Linux VM filesystem/process tests are
separate. Native/VM RSS and timing must not be pooled.

## Required exploration gates

A. A real fixed read snapshot precedes additional commits. Exactly its committed
ledger set is backed up; an open uncommitted transaction is absent. Source writers
continue committing; WAL growth, reader release and cancellation/timeout evidence
are recorded. An ordinary long read is not a promise of zero write interference.

B. A backup is standalone and hash/content verified. Advance the source after
backup; restore must still return the older snapshot from a distinct managed
inode. Restore actually creates a new copy and the fixed read-only HTTP application answers with correct identity,
count and watermark. Missing source, wrong identity/schema, FK errors, truncated
and structurally valid-but-old/empty content fail. Query/restore-to-first-HTTP
times and point RSS are observations, not SLOs or peak-memory claims.

C. Kill a real controller at copy completion, publication intent, after rename,
after catalog commit, restore materialization, deletion intent and after unlink.
A live old copy worker blocks replacement through the real inherited kernel lock.
After it exits, only formal recovery reconciles the operation. No partial or
mutable object becomes AVAILABLE, no duplicate object, no unknown occupancy
released. Stale epoch/current revision and current epoch/stale revision are
separately rejected without state effects; retired attempt phase updates reject.

D. Use a finite ext4 loop filesystem in a disposable Linux VM. Fill it only after
admission and actual snapshot establishment; real ENOSPC must fail the operation
and prevent new durable authority while full. Previous usable contents survive.
A real readonly bind remount over an already-running controller and actual SQLITE_FULL page cap likewise refuse success.
After explicit repair, formal recovery and new backups succeed. Loop mount,
worker/view processes, VM and data disk must be removed. Soft admission, pin and
receipt caps are also challenged by portable tests.

## Full MVP still requires

- Persistent local controller socket and bounded queue, request IDs/dedup window,
  phase/status/cancellation API, without replay after bounded history eviction.
- Coalescing fixed-interval scheduler and count-plus-age policy with explicit
  stale/retention exceptions and a bounded tombstone lifecycle.
- Supervised restored readers and pin-release protocol; no caller may delete an
  in-use instance merely because a controller restarted.
- Hardened readiness/repair CLI and installation/service lifecycle documentation.
- Wider repeated load and resource-growth qualification with declared limits.
- A defined application-profile interface; current fixed ledger is the only
  application contract tested. Multi-DB atomicity, NFS, generic arbitrary SQL,
  production replacement and failover are excluded.

Record actual SQLite runtime/source ID/build options. Python >=3.12 alone is not
qualification. Use a runtime with the official WAL-reset fix; unsupported
versions fail preflight rather than silently continuing.

Sudden power loss, VM reboot, physical storage/WAN behavior, disaster recovery
from same-device copies, remote storage, encryption and point-in-time recovery
are not qualified by these four gates.
