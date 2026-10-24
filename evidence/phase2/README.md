# Guarded restore and reader qualification

These receipts qualify their recorded source only. See [current bounded closeout
evidence](../closeout/README.md) for the delivered version.

Historical phase-two final run: `e8fedba95aa877d3`, recorded 2026-10-24T07:46:28.017668+00:00.
Source fingerprint: `14caafa5374accbb5b87e68b9b22cf67b695e93ac795ca85fc5046d652a60ca0`.

- [Complete JSON](latest.json) / [matching HTML](latest.html).
- [Native macOS](native-unit.json) and [installed Linux](linux-unit.json):
  **74 identical test IDs per platform**, zero failures/errors/skips.
- **10 actual Linux service scenarios**, **29 rejected report mutations**.
- Installed wheel modules match the frozen source manifest. Uploaded product
  source was moved out of import reach; linked SQLite 3.54.1 library hash/mapping
  matches its official-source build receipt. Native linked SQLite: 3.53.1.
- Fresh isolated Colima Linux VM, no host mounts. All **17** owned scenario
  service processes exited; Linux `/proc` found no remaining service/worker/reader
  command lines. Actual readonly mount, VM and data disk removed; preexisting
  profiles/status unchanged. Zombie-only entries, if present, hold no reader FDs.

| Formal service scenario | Observed result |
|---|---|
| Restore/start/query/stop/release | Exact 40-entry snapshot; backup hash unchanged; live release rejects, pin stays 1 until safe release then 0 |
| Authority with free guard | After stop, stale revision and missing token explicitly reject; failure cannot be masked by a busy guard |
| Controller SIGKILL with serving reader | New controller starts, old reader still queries 40 entries; ORPHAN_BUSY, pin/copy retained; no duplicate start/restore |
| SIGSTOP orphan | Busy guard retains copy/pin; unknown PID not signalled by controller; only independent exit allows release |
| Controller crash before spawn | Barrier proves no spawn yet; READY after restart, pin retained until release |
| Controller crash after spawn | Reader remains alive with instance guard; ORPHAN_BUSY after restart |
| Controller crash before reader readiness | Actual child held before ready; missing handshake retains ORPHAN_BUSY, never frees occupancy |
| Readiness deadline | Actual child held before ready; TimeoutError; separate-FD guard is free and owned PID absent **before any stop**, pin retained, later explicit stop/release succeeds |
| Owned reader stop timeout | SIGSTOP delays handled SIGTERM; STOP_REQUESTED is not exit, release refuses until process exits |
| Crash at release intent | Copy present before restart; recovery finishes deletion/sync, RELEASED and single unpin |
| Incomplete unauthenticated HTTP header | Reader itself closes idle connection before the test closes it; fixed query, stop and release still work |
| Actual readonly release and repair | EROFS 30; pin 1 and startup refuses until unmount; formal recovery then pin 0 |

The ten scenarios combine some assertions in the same run. Unit tests separately
inject exec, wrong query identity, ineffective kill, unlink and parent-fsync faults (including absent
copy with unsynced parent). These injections are not physical storage failures.
When kill is ineffective, the actual child/copy/pin and busy guard remain, and
release refuses until a real stop proves exit; this is not an uninterruptible
kernel-task test. A real-catalog regression also verifies bounded status history keeps active
references, total counts and token accessible within the socket frame limit.

## Point measurements in this Linux VM

Workload: one backup of a generated 40-entry ledger, a distinct verified restored
copy, one reader and a real loopback HTTP query. Start timing begins at the client
reader-start helper after restoration and ends when its start response arrives
after the successful readiness query. It includes the preliminary status/token
RPC, socket/service scheduling, content verification and process startup.
It excludes backup and restore-copy construction.

| Observation | Value |
|---|---:|
| Start through first verified query response | 51.00 ms |
| Reader RSS after query, `/proc/PID/status` VmRSS | 21072 KiB |
| Controller RSS at the same point | 23948 KiB |
| Managed logical file bytes while serving | 427316 bytes |

These are single VM point observations, not latency bounds, peak RSS, native
macOS performance, long-run growth or comparisons. RSS is not added across
processes as unique physical memory. File logical bytes are not filesystem/device
usage or reserved capacity; source WAL is outside the managed-store byte budget.
Native and VM samples are not pooled. Earlier exploration timings remain historical.

## Attempts and limits

[Attempt ledger](attempts.json) records four superseded successful VM runs with
then-current source/contracts; their original JSON/HTML are retained as
`attempt-01` through `attempt-04`. They do not qualify the later assertions.
[Development regressions](development-regressions.json) is a manually summarized,
sanitized record of pre-fix failures, explicitly not a qualification receipt.
Raw logs/private paths, package wheels, databases and VM images remain ignored.

This slice has one copy and one fixed-profile reader. Controller restart retains
orphan occupancy; there is no forced reader adoption or stale-PID termination.
Guard inodes/tombstones remain charged under finite catalog/receipt limits;
long-term GC/rollover is not qualified. No scheduler, age retention or production
source-database replacement. **VM reboot and sudden power loss were not tested.**
No boot-zero-gap, physical-storage or disaster-recovery guarantee follows.
[Implementation and reproduction](../../docs/PHASE2.md).

## Review corrections

[Review and repair](../../docs/PHASE2_REVIEW.md) records the inherited idle HTTP
blocking issue and the old deadline-test gap. [Sanitized review baseline](review-baseline.json)
is explicitly a manual summary, not a qualification receipt. A no-op-kill mutation
that passed the old case now fails before any stop can repair cleanup. Attempt 04
is retained with its original weaker evidence contract, not relabelled as passing
the new assertions. Current JSON/HTML require both deadline exit proofs and idle EOF.

The 0.5-second accepted-socket limit is an **inactivity** limit, not a total request
deadline or DoS guarantee. Continuous slow input and repeated local connections
remain outside the tested protection. This VM's bootstrap took about 252 seconds,
within the unchanged 300-second create deadline; setup time is recorded separately
and excluded from the reader-start point observation.
