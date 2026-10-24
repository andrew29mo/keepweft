# Phase-one review and repair

Two independent read-only passes examined logic and evidence before repair. A
follow-up checked the repair diff; agent agreement is not runtime evidence. The
current qualification is installed-package VM run `0f179d56578d7b8f`: 57 tests
on each platform, 13 VM scenarios and 27 report corruption controls. Its readonly
mount was removed, 22 owned services exited, no service/worker remained in the
VM, and the VM/data disk was deleted.

## Confirmed defect: deletion intent was reported as completion

The previous implementation computed retention_deleted from IDs that left
AVAILABLE. A failed unlink or parent-directory sync leaves DELETING, so a FAILED
replacement could falsely claim the older backup was fully deleted. The service
correctly blocked further mutation, but the side-effect receipt was wrong.

Two targeted regression tests failed on the previous implementation and pass with
the fix. The [sanitized baseline](../evidence/phase1/review-baseline.json) is a manual
summary, not a VM pass receipt. Tests inject unlink/fsync errors into the formal
Controller/Requests code; they do not replace the backup implementation.

The repaired contract:

- retention_planned persists attribution before deleting a candidate.
- retention_pending contains known DELETING candidates. Files may still exist, or
  be absent while directory sync/catalog completion remains uncertain.
- retention_deleted contains only catalog-committed DELETED candidates. Leaving
  AVAILABLE, or merely seeing files absent, is insufficient.
- Lookup reconciles attribution with catalog state, filtering old false-completion
  entries. Repair/restart can advance pending to deleted without a new request.
- Recovery synchronizes the parent even if the object is already absent. Repeated
  injected fsync failure refuses startup rather than committing DELETED.

The Linux-specific scenario uses an actual readonly bind mount over the selected
older backup, proves EROFS with an unlink, runs the formal service through deletion
failure, checks pending/not-deleted and preserved files, and verifies startup still
refuses before repair. After unmount, formal recovery completes deletion, preserves
the latest backup hash, and exact retry returns the same failed operation.
This is not hardware I/O failure, VM reboot or abrupt-power-loss qualification.

## Evidence gaps closed

Generation testing now checks all four just-retired receipt lookup/exact-submit
pairs, including a nonempty generation at the advance/crash boundary. Operation IDs
must remain unchanged and current inventory must not change on retry. Older
receipts expire while the previous generation survives. A recorder reporting zero
retained receipts is rejected, rather than merely satisfying an upper bound.

The deadline case must observe the before_publish barrier and record a real
TimeoutError under a declared one-second operation deadline. An unrelated FAILED
result no longer qualifies as a timeout test. Report corruption controls challenge
both witness and cause, along with pending/deleted and readonly mount cleanup.

## Scope

Portable error-injection regressions and Linux mount-fault scenarios are labelled
separately. Existing historical receipts remain versioned; the old 55/12/21 run
is retained as attempt-04, not rewritten as a pass under this stronger contract.
See [current evidence](../evidence/phase1/README.md) and [reproduction](PHASE1.md).
No managed reader, scheduler, long-term artifact GC, VM reboot, power loss,
physical storage fault or boot-zero-gap qualification is added.

This review records the historical phase-one source and evidence. The later
single-reader implementation and qualification are described in [PHASE2.md](PHASE2.md);
this phase-one receipt is not relabelled as evidence for that newer source.
