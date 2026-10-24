# Phase-one request-service qualification

Historical phase-one final run: `0f179d56578d7b8f`, 2026-10-24. Recorded source fingerprint:
`3274d3ea67f2bfa7d2a9ac2c9d29761e9bfd7f43dde2735fd2fb2a6f0390d894`.

- [Complete JSON](latest.json) and [matching HTML](latest.html).
- [Native macOS receipt](native-unit.json): 57 tests, zero failures/errors/skips.
- [Installed Linux receipt](linux-unit.json): identical 57 test IDs, zero failures/errors/skips.
- 13 actual service/worker scenarios, 27 rejected report mutations.
- Installed wheel modules matched source; uploaded checkout product was moved out
  of import reach. Linux actually loaded the hashed SQLite 3.54.1 library; native
  runtime was SQLite 3.53.1. VM had no host filesystem mounts.
- All 22 owned scenario service processes exited; Linux /proc scan found no
  remaining keepweft.service/keepweft.worker command lines. VM/data disk deleted;
  preexisting profiles/status unchanged.

| Scenario | Observed result |
|---|---|
| Exact retries / conflict / service restart | Same operation, one object; changed payload conflicts; missing old-epoch ID refuses |
| Receipt-full legacy core regression | keep=2/max_receipts=2 third refusal preserves both backups and their hashes |
| Saturated queue and receipts | Rotate BUSY; queued cancel completes and active cancel persists without another slot; no publication/staging |
| Cancel before publish intent | CANCEL_ACCEPTED then CANCELLED, zero objects |
| Cancel after publish intent | TOO_LATE; SIGKILL/restart reconciles one AVAILABLE object |
| Generation rollover/GC | Three ordinary rollovers plus a crash after fourth advance; four just-retired receipts return the same operation, older keys expire without new work |
| Lost admission response | Same operation becomes FAILED after owner death before copying; no silent re-execution |
| Lost rename/catalog response | Same operation recovers AVAILABLE with one object |
| Durable cancellation then crash | Recovery ends CANCELLED, no object |
| Deadline before intent | before_publish observed and TimeoutError confirmed under a one-second deadline; FAILED, no object, staging cleaned |
| Crash immediately after retention deletion | Failed replacement still reports deleted predecessor; latest preserved |
| Actual readonly retention failure/repair | EROFS 30; pending=1/deleted=0, files preserved and startup refused; after unmount/recovery pending=0/deleted=1, same operation and latest hash |

While a worker was deliberately held and the queue/receipts were full, one status
request took 37.26 ms in this VM. This is a single controlled response observation,
not a throughput comparison, latency bound, failover RTO, native/VM comparison or
new RSS claim. Timing includes socket/service scheduling. SQLite verification and
filesystem/catalog syscalls can still stall the service.

[Attempt ledger](attempts.json) preserves provenance instead of replacing failures:

- Sandbox preflight failed ten service tests because socket bind was denied; it
  is an environment failure, not a product pass. Aggregate receipt retained;
  raw private paths/logs are not uploaded.
- [Attempt 1 JSON](attempt-01.json) / [HTML](attempt-01.html): VM bootstrap timed
  out at 180 seconds, before any product tests. VM/data disk cleanup succeeded.
- [Attempt 2 JSON](attempt-02.json) / [HTML](attempt-02.html): earlier source and
  contract passed 52 tests/platform and 11 scenarios. Superseded by retention
  attribution and process-cleanup strengthening; not final qualification.
- [Attempt 3 JSON](attempt-03.json) / [HTML](attempt-03.html): 54 tests/platform,
  12 scenarios; superseded by the explicit stopped-service cleanup-timeout control.

- [Attempt 4 JSON](attempt-04.json) / [HTML](attempt-04.html): original phase-one
  55 tests/platform, 12 scenarios and 21 controls. Superseded by the reviewed
  deletion-pending fix, retained-generation and deadline assertions.
- [Review regression baseline](review-baseline.json): manually summarized two
  expected injected-error failures before repair, then passing targeted tests.
  Parent-fsync errors are injected unit tests, not physical I/O failure evidence.

[Review findings and repair](../../docs/PHASE1_REVIEW.md) describes the changes.

Historical successful runs use their own recorded source/contract, not the current
stricter verifier. This directory qualifies only the recorded phase-one source; newer reader
qualification is retained separately in ../phase2/. [Reproduce](../../docs/PHASE1.md#evidence-scope-and-reproduction).
No service installation/systemd, managed reader, scheduler, long-term metadata
rollover, VM reboot, abrupt power loss or boot-zero-gap claim is established.
Original four-exploration evidence and measurements remain separately historical.

The guarded reader added later is separately qualified in [phase two](../phase2/README.md).
