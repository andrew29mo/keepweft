# Keepweft

A local SQLite backup and validated-restore controller. This repository currently
contains a bounded MVP: **a backup request service, conservative capacity and
retention handling, and one guarded validated restored reader**. Earlier broader
service designs remain a roadmap, not delivered capabilities.

The core takes a bounded read snapshot, creates a standalone backup through
SQLite's Online Backup API, verifies a fixed application contract, and publishes
it through a persistent catalog. A restore creates a separate copy. It never
replaces the live source database.

## Scope

- One registered local WAL-mode database; fixed `ledger-v1` application profile.
- Online snapshot, worker cancellation/deadline, immutable object IDs, publication
  intent, recoverable deletion, pins, count retention and conservative capacity admission.
- Single-controller kernel lock, deliberately inherited by copy workers. An old
  live worker blocks takeover; uncertain occupancy never becomes free capacity.
- Actual epoch/revision rejection and crash reconciliation in the same core used
  by the CLI. Same-UID processes are trusted; this is not a hostile-worker sandbox.
- One guarded read-only restored ledger: start, real query, stop and safe release;
  a live/unknown reader retains its copy and backup pin across controller crash.

No selected license is granted for the project yet. The GitHub repository must
remain Private. External Python/SQLite dependencies retain their own licenses;
see [third-party scope](docs/THIRD_PARTY.md).

## Run locally

Python >=3.12 is required, together with a SQLite runtime containing the WAL-reset
fix. `python -m keepweft.cli runtime` reports and checks the actual linked runtime.
For qualification we use native SQLite 3.53.1 and an externally built SQLite 3.54.1
in the isolated Linux VM; a Python version alone does not qualify SQLite.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m tools.unit --output results-unit.json
```

Use canonical absolute paths (resolve `/tmp` or `/var` aliases on macOS). The
source must be outside the owner-only managed store. `init-source` creates only
the demonstration ledger; existing databases must not be overwritten.

```sh
python -m keepweft.cli init-source --source /absolute/path/live.sqlite --count 20
# Use the returned UUID for the first backup; later commands read registered policy.
python -m keepweft.cli backup --root /absolute/path/store \
  --source /absolute/path/live.sqlite --uuid RETURNED_UUID
python -m keepweft.cli status --root /absolute/path/store
python -m keepweft.cli restore --root /absolute/path/store --id BACKUP_ID
python -m keepweft.cli diagnose --root /absolute/path/store
```

Each exploration CLI invocation acquires a new authority epoch and is synchronous.
For durable backup request deduplication, bounded generation history and
cancellation/publication semantics, use the separate [phase-one service and
saved-envelope CLI](docs/PHASE1.md). For restore/start/query/stop/release, use the
[guarded-reader workflow](docs/PHASE2.md) on the same service. Scheduling remains
future work; reader mutations require explicit current epoch/revision tokens.

## Current results

The final bounded closeout passed **79 identical tests on each platform**, repeated
**10 Linux reader/fault scenarios**, **four closeout scenarios** and **two normal
VM reboots**, with **48 rejected report corruptions**. The clean no-host-mount VM
installed the wheel and verified its module/runtime hashes before using it.

Twenty-four complete cycles ran for **124.04 seconds** in one controller process,
including at least five seconds of live reader dwell per cycle. Controller RSS was
21,088 KiB initially, 28,488 KiB after the declared four-cycle warmup, and 29,396 KiB
at the maximum/end: a **908-KiB post-warmup increase**, within the predeclared
4,096-KiB allowance. This is sampled Linux VM RSS, not a flat-memory claim,
continuous peak, native measurement or long-term bound. Quiescent FDs stayed at 7;
remaining children, active restores, readers and pins were zero after every cycle.
Metadata grew as expected; 24 fixed guards and 24 ready hints remain, alongside
retained rows. There is no automatic guard/tombstone GC.

Separate receipt and soft logical-capacity refusals preserved existing backups
and allowed query/stop/release. Two normal reboots preserved the catalog and copy
unchanged **after boot before controller startup**, then the formal service
reconciled a formerly serving copy and an interrupted release respectively.
This tests recovery when the service is explicitly started after boot; it is not
a systemd-autostart, abrupt-power-loss or boot-zero-gap qualification.
See [closeout evidence and retained failed/superseded attempts](evidence/closeout/README.md).

The historical guarded-reader slice passed **74 tests on each platform**, **10 Linux service
scenarios** and **29 report corruption controls**; see [phase-two evidence](evidence/phase2/README.md).
It tests controller crashes around spawn and release, paused readers, safe pin
retention and real Linux readonly deletion/repair with the installed package.
Unknown orphan processes are retained and never signalled by persisted PID.


The historical phase-one backup-request slice passed **57 tests on each platform**, **13 Linux
fault scenarios** and **27 report corruption controls**. Exact retries, generation
GC, cancellation on both sides of publication intent, and retention attribution
after a crash use the actual service/worker implementation. A real Linux readonly
mount challenges pending deletion and repair; injected fsync regressions stay
separately labelled. See [phase-one
JSON/HTML evidence](evidence/phase1/README.md). These historical results qualify their source-bound slice only.

The historical installed-core exploration passed all four probe groups. Native macOS
and isolated Linux each passed the same **30 portable tests**, with **24 rejected
report corruptions**. A source that advanced from 192 to 224 committed entries
still produced the exact earlier snapshot; restored application queries distinguish
the old snapshot from the newer live source. Real ENOSPC, readonly bind-mount and
SQLite FULL faults fail safely and permit new work after explicit repair.

The historical exploration small-ledger trial took 28.98 ms to back up and 36.71 ms to restore
through the first loopback HTTP query. These are single controlled VM observations,
not performance comparisons, SLOs or physical-storage guarantees. Failures, RSS,
disk-accounting values and full receipts are retained below.

## Evidence and design

- [Bounded closeout and operator workflow](docs/CLOSEOUT.md)
- [Retained exploration evidence](evidence/README.md) (historical four explorations)
- [Phase-one implementation and qualification](docs/PHASE1.md) (historical slice)
- [Guarded-reader implementation and qualification](docs/PHASE2.md)
- [Reader review findings and repair](docs/PHASE2_REVIEW.md)
- [Architecture and state machines](docs/ARCHITECTURE.md)
- [Reviewed service design decisions](docs/MVP_DESIGN.md) (design only)
- [Planned state machines and recovery matrix](docs/MVP_STATE_RECOVERY.md)
- [MVP acceptance and remaining work](docs/MVP_ACCEPTANCE.md)
- [Reproduction and measurement boundaries](docs/VALIDATION.md)

An online snapshot is not a backup of external files, multiple ATTACHed databases
or another host. Same-device copies do not protect against device loss. Abrupt
power loss, physical storage behavior, encryption, remote storage,
point-in-time recovery and production service cutover are unqualified.
