# Keepweft

A local SQLite backup and validated-restore controller. This repository currently
contains a **minimal production core and four technical explorations**, not the
complete operational MVP.

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
- A fixed read-only HTTP application endpoint for querying a restored ledger.

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

Each CLI invocation acquires a new authority epoch; the current exploration CLI
is synchronous. A future persistent control socket and scheduler are separate
MVP work. Repeating an operation after a lost response requires status inspection;
this slice does not implement a general client retry/deduplication API.

## Current results

The final installed-core exploration passed all four probe groups. Native macOS
and isolated Linux each passed the same **30 portable tests**, with **24 rejected
report corruptions**. A source that advanced from 192 to 224 committed entries
still produced the exact earlier snapshot; restored application queries distinguish
the old snapshot from the newer live source. Real ENOSPC, readonly bind-mount and
SQLite FULL faults fail safely and permit new work after explicit repair.

The ordinary small-ledger trial took 28.98 ms to back up and 36.71 ms to restore
through the first loopback HTTP query. These are single controlled VM observations,
not performance comparisons, SLOs or physical-storage guarantees. Failures, RSS,
disk-accounting values and full receipts are retained below.

## Evidence and design

- [Retained exploration evidence](evidence/README.md)
- [Architecture and state machines](docs/ARCHITECTURE.md)
- [MVP acceptance and remaining work](docs/MVP_ACCEPTANCE.md)
- [Reproduction and measurement boundaries](docs/VALIDATION.md)

An online snapshot is not a backup of external files, multiple ATTACHed databases
or another host. Same-device copies do not protect against device loss. Abrupt
power loss, VM reboot, physical storage behavior, encryption, remote storage,
point-in-time recovery and production service cutover are unqualified.
