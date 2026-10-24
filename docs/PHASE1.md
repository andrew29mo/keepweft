# Phase one: durable backup requests

This slice implements backup requests only. It adds a persistent Unix-socket
control service around the same Controller/worker used by the exploration CLI.
Managed restore readers, scheduling, age retention, service installation/systemd
and general object/tombstone GC remain future work. The project is Public and [MIT licensed](../LICENSE).

## Run and retry

Use a qualified Python/SQLite runtime as described in README.md. Prepare the demo
source with the existing init-source command, then start the service in foreground:

```sh
python -m keepweft.service --root /absolute/store \
  --source /absolute/live.sqlite --uuid SOURCE_UUID
python -m keepweft.client status --root /absolute/store
python -m keepweft.client prepare --root /absolute/store --envelope /absolute/request.json
python -m keepweft.client submit --root /absolute/store --envelope /absolute/request.json
python -m keepweft.client lookup --root /absolute/store --envelope /absolute/request.json
python -m keepweft.client cancel --root /absolute/store --envelope /absolute/request.json
```

Prepare uses exclusive file creation, fsync of file and parent directory, and sends
no backup. Keep this exact envelope after lost responses. Repeating submit returns
the existing operation when retained; changing its command conflicts. Do not create
a new envelope automatically after RETIRED / RESULT_GONE. A new envelope is a new
user intention, not deduplication of an old one. Receipt state records the
operation outcome; it does not resurrect an artifact later removed by retention.
Envelope paths are outside the
managed store. CLI errors/transport disconnects are not proof of no side effects.

The owner-only store and socket grant access to trusted same-UID processes. The
service runs without root; Linux qualification uses root only within a disposable
VM. Only backup(kind,timeout) is supported. No arbitrary SQL, shell or worker result
submission. Do not run the synchronous exploration mutation CLI against a service;
the global lock refuses a competing owner. Once stopped, that older CLI still has
its exploration semantics rather than the request protocol.

## Admission and bounded history

Envelope: epoch, generation, 32-hex request_id and explicit command. Canonical
command digest normalizes numeric timeout. Retained exact-key lookup happens
before stale authority rejection and returns only the existing receipt. A missing
old epoch/generation never admits new work. New receipt + QUEUED op commit in one
catalog transaction before admission response and before retention/worker activity.
The admitted operation is not guaranteed space: dispatch checks capacity again.
No config mutation API exists in this slice; registered source/config is fixed.

Limits: 16 queued requests maximum (test/configurable downwards), one active backup,
eight clients, 64 KiB frame, two-second incomplete-client timeout, and configured
max_receipts per generation (default 128). Socket reads/writes are nonblocking;
status/cancel are pumped during worker waits and before publication. SQLite
verification/fsync/catalog syscalls are synchronous: kernel/storage stalls can
still delay control responses. This is not a universal control-latency guarantee.

Explicit rollover uses a saved envelope only for its epoch/generation:

```sh
python -m keepweft.client rotate --root /absolute/store --envelope /absolute/request.json
```

All operations must be terminal with no unreconciled staging and no active backup.
The generation increment commits before historical deletion. Keep current plus one
retired generation; a third rollover forgets older receipts. Retained receipt GC
also removes its terminal backup operation row, but backup objects/manifests remain
in their separate catalog. Generations do not reset across service restart; epoch
advances and QUEUED requests become INTERRUPTED rather than execute unexpectedly.
Old accepted publication intents are reconciled by the formal Controller recovery.
If rollover cannot progress, new admission refuses rather than silently evicting.

This bounds request/backup-operation history only. Backup deletion tombstones and
other exploration metadata are not yet fully garbage-collected. Catalog page cap
still causes explicit exhaustion; this slice does not claim unlimited longevity.
Global monotonic object-ID allocation and guarded reader lifecycle from the design
remain future work; current artifacts use existing random IDs and no-replace checks.

## Cancellation and publication

Cancel targets the existing saved envelope; it needs no extra queue/receipt slot.
A QUEUED request becomes CANCELLED immediately. An active request durably records
cancel_requested and returns CANCEL_ACCEPTED. Only worker exit, staging deletion
and directory sync permit terminal CANCELLED. The flag survives controller death;
startup reconciles interrupted work before presenting its final cancellation.

At the publication boundary, the controller pumps requests, checks cancellation
and deadline, then commits PUBLISHING without another event pump between check and
commit. If cancellation won, it cannot publish. If PUBLISHING won, cancel returns
TOO_LATE; normal completion or recovery publishes exactly that operation ID.
CANCEL_ACCEPTED is not yet CANCELLED. Client disconnect is not cancellation.
A lost response after publication can still mean a successful backup.

Legacy cancel-file callers also receive a final cancellation check before intent.
No cancellation-after-publication undo is implemented. A signal-driven graceful
stop closes admission and requests cancellation of pre-intent active work; process
SIGKILL instead relies on lifetime lock + persisted recovery state.

## Retention ordering fix

The exploration backup path now checks receipt capacity and predictable space
before pruning, creates an operation record, then performs retention as part of
that operation. Service admission likewise creates its durable receipt before any
prune. Dispatch capacity refusal creates a FAILED receipt without pruning.

Accepted work may delete eligible older backups then fail later; this is not an
atomic rollback of retention. Latest/pinned objects remain protected. The receipt
lists retention_deleted only after catalog-committed DELETED, and
retention_pending while deletion/sync remains unfinished. Pruning attribution is
persisted before deletion and reconciled against the backup catalog, including a
crash immediately after deletion. Recovery syncs the parent even when the files
are already absent; a repeated sync error must refuse startup. Receipt-full rejection
must preserve old files and contents; tests explicitly cover keep=2/max_receipts=2.

## Evidence scope and reproduction

The phase-one runner uses a fresh no-host-mount Colima VM, installs the wheel,
removes the importable source package from the uploaded checkout, compares module
hashes, and verifies the actual loaded SQLite library. It runs identical portable
tests on macOS/Linux and additional real-service fault scenarios in Linux.

```sh
python -m pip wheel --no-build-isolation --no-deps . -w results/phase1-wheel
python -m tools.phase1_validate \
  --colima-home /absolute/colima-home --toolchain /absolute/toolchain/bin \
  --profile keepweft-exp-p1-UNIQUE \
  --wheel results/phase1-wheel/keepweft-0.1.0-py3-none-any.whl \
  --output results/phase1-UNIQUE
```

Dedicated profile/data disk must not already exist. The subprocess harness forcibly reaps a service if graceful cleanup times out
and propagates that timeout as failure; a SIGSTOP control challenges this path.
VM creation uses an explicit
VM hostname/local DNS mapping and a 300-second bootstrap bound; test-stage bounds
are unchanged. The first 180-second bootstrap timeout remains a failed setup
receipt, not a Linux product pass. Runner has bounded stages and
retains failure records, then deletes only its VM/data disk. Private command logs
stay ignored; sanitized JSON and corresponding HTML are retained in evidence/phase1.
The report verifier rejects missing stages, skipped tests, source mismatch,
incorrect cancel/GC results, unsupported qualification flags and cleanup failure.

Fault cases deliberately stop processes at real admission, before-intent,
publish-intent, rename, catalog and generation-advance boundaries. These are
controlled process crashes, not VM reboot or power loss. Status timing is a single
controlled observation while a worker is held; no throughput or SLO claim follows.
The original four-exploration receipts remain historical, source-bound evidence.

## Current qualification

Run `0f179d56578d7b8f`: 57 identical tests on macOS/Linux, 13 Linux real-process
scenarios and 27 rejected report corruptions. The stopped-service harness control
proves timeout propagates after forced reaping, not graceful-success relabelling.
See [review and repair](PHASE1_REVIEW.md), [receipts and retained attempts](../evidence/phase1/README.md). No new throughput
comparison, RSS bound, scheduler, reader-lease, reboot or power-loss qualification
is claimed. Historical four-exploration measurements remain source-bound history.

## Later guarded-reader slice

The backup protocol/evidence above is the historical phase-one qualification.
The same service now also supports the separate [guarded reader workflow](PHASE2.md).
Earlier statements that readers are future work describe the phase-one boundary.
