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

## Reviewed service MVP: phased qualification

Design authority: [decisions](MVP_DESIGN.md), [states/recovery](MVP_STATE_RECOVERY.md).
The following remain full-MVP acceptance targets. The backup-request subset is
implemented and separately qualified in [PHASE1.md](PHASE1.md); a subset pass does
not mark the broader row complete. Existing 30-test/platform exploration receipts
do not qualify a persistent service. Scheduling, managed readers, time retention,
artifact GC and installation/systemd remain pending. Source/config mutations are
unsupported; phase one does not qualify dynamic source prevalidation before prune.

| Gate | Required challenge and acceptance evidence |
|---|---|
| Admission before side effects | Queue/receipt full, stale token, digest conflict and invalid source reject without deletion/reservation/child. Specifically keep=2/max_receipts=2: a rejected third request must not prune; if rollover permits admission, a new durable receipt must precede pruning. Accepted pruning reports committed deletions even when copy later fails, with DELETING reported separately as pending. Unlink/parent-sync faults and repair must preserve attribution; absence alone cannot complete deletion. |
| Lost responses and dedup | Drop responses after admission, intent, rename and AVAILABLE commit; exact retry returns same operation, at most one artifact, no repeat prune. Different payload under same key conflicts. |
| Receipt rollover | Fill current generation; unresolved operation blocks rollover. Crash before/after durable generation advance and during GC; forgotten old keys never execute; each just-retired receipt must remain queryable and exact retry must return the same operation, including advance/crash/restart. CLI never silently replaces stale/GONE envelope. Bound retained generations/bytes. |
| Queue and revisions | Queue work while another operation advances revision; accepted work uses its own attempt authority. Changed source/policy/target refuses explicitly at dispatch. Slow copy does not block bounded status/cancel; fill queue and receipts simultaneously and confirm cancel needs no new slot. |
| Cancel versus publication | Force both serialized orderings around durable intent, then crash. Cancel wins => no publication and CANCELLED only after exit/cleanup; intent wins => TOO_LATE and same-ID reconciliation. Client disconnect alone does not cancel. |
| Reader handoff | Kill controller before spawn, after exec, before/after real HTTP readiness and during release. Live reader still answers exact snapshot; no second reader, deletion or pin release. SIGSTOP reader keeps guard busy; only actual exit allows cleanup. Exec failure and missing handshake must eventually clean after proven child exit without restarting controller or retaining its own FD. Test real cross-process locks, not just mocked booleans. |
| Orphan occupancy | Restart near byte cap with busy reader guard. Bytes/pin/reservation remain counted, no excess admission. Separate reader guard allows global controller recovery. No stale-PID kill. |
| Capacity and repair | Formal service on finite VM filesystem: ENOSPC, EROFS, SQLite FULL and sync/delete/release failure. No false success/new mutation; protected backup survives, explicit repair/restart reconciles. Software policy and filesystem faults reported separately. |
| Retention and freshness | Pinned older backup + latest blocks new backup; source continues changing. Service reports stale/blocked, bounded retries. Release pin triggers at most one coalesced retry. Count/age cannot override latest/pins. |
| Time | Forward/backward wall-clock changes and restart do not reorder latest, mass-prune, present old data as fresh, or flood queue. Monotonic age restarts conservatively; freshness unknown until established. |
| Bounded metadata | Exercise at least three receipt-generation rollovers and repeated object/guard cleanup with files, rows, bytes and locks counted. After guard/row GC and restart, allocator never reuses an ID and old operations cannot recreate a guard. Failed cleanup remains charged. No unbounded logs or tombstones; capped exhaustion visible. This is bounded evidence, not long-term proof. |
| Verification contract | ledger-v1 only: exact snapshot identity/watermark/content, structure/FK and distinct restore query required. Wrong/unsupported profile refuses, NOT_RUN cannot become application PASSED. |
| Service lifecycle | Clean isolated VM installs the built package by documented procedure, starts/stops/restarts service; socket permissions, paused state, children, inherited locks and recovery match design. Native portable tests and Linux service results stay separate. |
| Reports | JSON/HTML derive from same typed receipt; include installed source/runtime fingerprints, actual fault/cleanup, each assertion and failed attempt. Timeout/skip/missing evidence never passes. Timing/RSS sampling method and VM scope explicit. |

Resource limits in MVP_DESIGN.md are proposed bounds, not measured recommendations.
Choose and declare workload/duration before each resource trial. Report starting,
maximum and ending RSS, catalog/log/guard/file counts and allocated/logical bytes;
do not restart processes mid-trial to hide growth. A trial stopped by a capacity
limit reports that limit, not successful continuous operation.

Implementation order: admission/dedup/cancel; guarded reader lifecycle;
scheduler/retention/metadata; packaged service and isolated fault qualification.
No generic schema mode, external reader supervision, live production replacement,
remote storage or multi-database atomicity is part of this service MVP.

Record actual SQLite runtime/source ID/build options. Python >=3.12 alone is not
qualification. Use a runtime with the official WAL-reset fix; unsupported
versions fail preflight rather than silently continuing.

Sudden power loss, VM reboot, physical storage/WAN behavior, disaster recovery
from same-device copies, remote storage, encryption and point-in-time recovery
are not qualified by these four gates.
