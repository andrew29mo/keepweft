# Architecture: exploration core and intended MVP

This page describes the implemented exploration core. The reviewed next-service
design is in [MVP decisions](MVP_DESIGN.md) and [state/recovery matrix](MVP_STATE_RECOVERY.md).
Those documents supersede earlier prospective MVP sketches, not the implementation
claims below. The first backup-request slice is implemented in [PHASE1.md](PHASE1.md); scheduling
and managed restored-reader ownership remain unimplemented. Historical core details
below must be read with that explicit scope.

## Trust and ownership

The source is one existing, registered local SQLite main database. Its path and
ledger UUID are trusted configuration; source replacement while active is
unsupported. The controller uses mode=ro/private-cache and never opens a live
source with immutable=1, copies its WAL/SHM as ordinary files, changes its journal
mode, or creates a missing source. Only the local `ledger-v1` profile is currently
implemented. Generic schemas cannot be labelled application-verified.

Controller, worker and profile code run as a trusted same-UID user, not root in a
normal installation. VM root is used only for isolated loop-filesystem faults.
The current design does not contain malicious same-UID code. Profiles contain
fixed SQL, no user SQL/shell/extension hooks.

## Snapshot and closure

A dedicated source connection opens BEGIN, then the first UUID SELECT establishes
its read snapshot. Schema, committed sequence and content digest come from that
same connection; backup copies from it. The SQLite read transaction remains open
until copying completes or the worker ends. A long reader can grow the source
WAL. Deadline and WAL-growth checks stop this reader, not every other reader or
writer on the machine. The WAL budget is a sampled guard, not a source-filesystem
hard quota.

The worker normalizes only its own target to DELETE journal mode and closes all
SQLite handles. The controller waits/reaps before examining the result. It
rejects unexpected sidecars, validates structure/foreign keys/ledger contents,
compares the exact snapshot watermark/digest and computes a file hash. All
read/write worker handles must be gone before publication. Rename alone would
not prevent an existing writer FD from modifying a published inode.

Implemented backup path:

`RESERVED -> COPYING -> SEALED -> PUBLISHING -> AVAILABLE`

SNAPSHOT_OPEN and VERIFYING are observable internal phases/barriers; they are
not yet separate persistent operation states. Controller mutations use a SQLite
catalog with FULL synchronous/DELETE journaling. The persistent publication intent
contains the exact manifest before same-filesystem rename. Files and both parent
directories are synchronized before AVAILABLE commit and success response.

## Recovery table

| Durable condition | Reconciliation after lifetime-lock acquisition |
|---|---|
| RESERVED/COPYING without publication intent | Remove only that known staging directory; mark failed |
| PUBLISHING with stage only | Recheck manifest, contents and hash, then publish and commit |
| PUBLISHING with final object | Recheck intent/object, commit exactly the same object ID |
| AVAILABLE after lost response | Preserve existing object; status is the result witness |
| DELETING | Finish known deletion and directory sync; then mark DELETED |
| Incomplete restore | Remove known partial copy, release pin, mark failed |
| READY restore | Verify it still matches its immutable backup contract |
| Missing/corrupt catalog, unexpected inventory or mismatches | Refuse writable startup; never reconstruct an empty catalog or auto-delete unknown data |

File/catalog operations are not one atomic transaction. A recovered publication
may legitimately complete a previously lost response. A failed CLI response alone
must not be interpreted as proof that no object was committed.

## Lock and stale authority

A fixed lock inode is never removed by the program. Controller and exec-started
copy worker share the same explicitly inherited open-file description. No path
calls LOCK_UN. The controller closes its descriptor; the copy worker deliberately
retains its inherited descriptor through interpreter/atexit shutdown, allowing
the kernel to close it only at process exit. A crashed controller with a live worker
therefore cannot be replaced by a new writer until the kernel releases the lock.
An uninterruptible or accidentally inherited descriptor can cause indefinite BUSY;
the implementation favors safety and does not force takeover.

Workers open SQLite after exec; connections never cross fork. Cancellation first
requests termination, then kill if necessary. Unknown exit sets CLEANUP_PENDING,
retains reserved occupancy and blocks mutations. This is a bounded decision,
not guaranteed bounded kernel-I/O cleanup. External SIGKILL bypasses user cleanup;
the inherited lock and persisted state carry recovery instead.

Epoch increases durably on each acquired controller lifecycle. New operations can
supply exact epoch/revision; checks precede pruning, reservation and copying.
Retired attempts cannot advance phases. Only the formal recovery routine may
reconcile a known prior-epoch intent. No arbitrary externally supplied worker
result may promote itself into AVAILABLE.

## Restore and deletion

Restore pins the original in one catalog transaction, copies to a unique new
managed directory, verifies exact hash and application data and executes the
fixed application query before READY. `view.py` serves only GET /summary against
that read-only copy. Its listener lifecycle is controlled by the current probe;
a supervised persistent instance/API is remaining MVP work. Callers must stop
readers before release; the exploration CLI does not yet manage reader leases.

Deletion refuses pinned and last/latest backups. DELETING intent is durable
before unlink; absence during recovery is idempotent. Persistent operations and
backups retain tombstones. The exploration CLI retains its explicit receipt-capacity refusal. The separate
phase-one backup service implements generation-based bounded receipt GC and saved
request idempotency; general artifact/tombstone GC remains future work. No unlimited
longevity claim applies.

## Capacity and policy

Default logical managed budget is 64 MiB; artifact cap 8 MiB; each copy/restore
conservatively reserves twice the artifact cap plus 1 MiB metadata headroom.
This covers one heavy operation, not a general concurrent multi-worker scheduler.
Allocation/free-space observations are separate from logical file bytes. SQLite
sidecars and staging count, and unknown occupancy is retained.

This admission budget is a soft software policy, not a filesystem quota. Copy
checks page count in 32-page batches; source snapshot size is fixed. Catalog,
filesystem and kernel I/O can still fail. Actual ENOSPC/EROFS is tested using an
isolated limited ext4 filesystem. Source DB/WAL/SHM are outside the managed budget.
All temporary files in the implemented data path are managed; no sorting profile
that spills arbitrary temp files is supported.

The count policy keeps at least two slots and protects latest/pinned objects.
Rotation may delete an eligible older backup before copying, while preserving the
latest. If pins prevent a slot, the new operation refuses. Age-based retention,
explicit stale-age warnings and persistent scheduling remain intended MVP work.
A SQLite/catalog error retires that controller from further mutation. A new
writable startup must persist a new epoch and complete reconciliation. Read-only
`diagnose` is explicitly not a readiness/recovery-success claim.

## Guarded reader slice

[PHASE2.md](PHASE2.md) describes the implemented single-copy reader lifecycle,
instance guard ownership, conservative orphan recovery and evidence. Older
exploration descriptions of caller-managed readers are historical. No scheduling,
forced orphan adoption or long-term guard GC is qualified by this slice.


## Bounded delivery boundary

[CLOSEOUT.md](CLOSEOUT.md) defines the current local MVP and its separate installed
workflow, capacity, resource and normal reboot evidence. Broader scheduling,
age-retention, automatic metadata GC and systemd packaging designs above are
deferred targets, not implied delivered features. Abrupt power loss and boot
zero-gap remain unqualified.
