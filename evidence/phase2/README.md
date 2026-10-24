# Guarded restore and reader qualification

Current run: `9beaeff8d7213078`, recorded 2026-10-24T07:33:10.493039+00:00.
Source fingerprint: `a6848abeb0e3d52e4c34dba2a063be924dc0953cf9198b7ee7e4d1a09a19f787`.

- [Complete JSON](latest.json) / [matching HTML](latest.html).
- [Native macOS](native-unit.json) and [installed Linux](linux-unit.json):
  **72 identical test IDs per platform**, zero failures/errors/skips.
- **9 actual Linux service scenarios**, **26 rejected report mutations**.
- Installed wheel modules match the frozen source manifest. Uploaded product
  source was moved out of import reach; linked SQLite 3.54.1 library hash/mapping
  matches its official-source build receipt. Native linked SQLite: 3.53.1.
- Fresh isolated Colima Linux VM, no host mounts. All **16** owned scenario
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
| Readiness deadline | Actual child held before ready; TimeoutError, owned child reaped, pin retained, explicit stop/release succeeds |
| Owned reader stop timeout | SIGSTOP delays handled SIGTERM; STOP_REQUESTED is not exit, release refuses until process exits |
| Crash at release intent | Copy present before restart; recovery finishes deletion/sync, RELEASED and single unpin |
| Actual readonly release and repair | EROFS 30; pin 1 and startup refuses until unmount; formal recovery then pin 0 |

The nine scenarios combine some assertions in the same run. Unit tests separately
inject exec, wrong query identity, unlink and parent-fsync faults (including absent
copy with unsynced parent). These injections are not physical storage failures.
A real-catalog regression also verifies bounded status history keeps active
references, total counts and token accessible within the socket frame limit.

## Point measurements in this Linux VM

Workload: one backup of a generated 40-entry ledger, a distinct verified restored
copy, one reader and a real loopback HTTP query. Start timing begins at the client
reader-start call after restoration and ends at the successful readiness query;
it includes socket/service scheduling, content verification and process startup.
It excludes backup and restore-copy construction.

| Observation | Value |
|---|---:|
| Start through first verified query | 34.29 ms |
| Reader RSS after query, `/proc/PID/status` VmRSS | 21068 KiB |
| Controller RSS at the same point | 23948 KiB |
| Managed logical file bytes while serving | 427310 bytes |

These are single VM point observations, not latency bounds, peak RSS, native
macOS performance, long-run growth or comparisons. RSS is not added across
processes as unique physical memory. File logical bytes are not filesystem/device
usage or reserved capacity; source WAL is outside the managed-store byte budget.
Native and VM samples are not pooled. Earlier exploration timings remain historical.

## Attempts and limits

[Attempt ledger](attempts.json) records three superseded successful VM runs with
then-current source/contracts; their original JSON/HTML are retained as
`attempt-01` through `attempt-03`. They do not qualify the later assertions.
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
