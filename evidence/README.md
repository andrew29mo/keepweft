# Historical four-exploration evidence

These receipts qualify the exploration source at commit `b3ab630`, not every later
revision. See [phase-one request-service evidence](phase1/README.md) for the new
backup request protocol. Historical JSON/HTML have not been overwritten.

# Four technical explorations: current evidence

Run `a22b4aab1b7182ce`, source
`4dcf53a7f4e6cd3e353fe15cc25da28a52dde2684c02aff713aae4156662ff7c`.

[Complete JSON](latest.json) · [Exact HTML](latest.html) ·
[macOS tests](native-unit.json) · [Linux tests](linux-unit.json) ·
[All attempts](attempts.json) · [Readonly diagnostic](readonly-diagnostic.json)

## Qualification

- Fresh Ubuntu 24.04 aarch64 VM: 2 CPUs, 3 GiB, no host directory mounts.
- Installed wheel's production module hashes equal the frozen source. Checkout
  product modules were moved out of import reach before tests/probes. The same
  Controller/data/worker modules handle normal and crash-recovery paths.
- Native macOS SQLite 3.53.1; Linux SQLite 3.54.1 built from the hash-verified
  official amalgamation. Actual loaded-library hash, mapping and source ID checked.
- **30 identical portable test IDs on each platform**, no failures/errors/skips.
- Four VM probe groups passed; **24 mutated-evidence controls** reject. Normal
  and optimized report verification and exact JSON/HTML correspondence checked.

## What was actually established

A: the reader fixes a snapshot at 192 committed transactions while another real
transaction is uncommitted. After it is rolled back, the source commits another
32 transactions; the completed backup still contains exactly sequences 1..192
and the source contains 224. The controlled long read grows WAL. Cancel and
timeout cases reap real workers and remove staging before releasing occupancy.

B: an ordinary 80-transaction backup is standalone and validated. The source is
then advanced to 81. A separate restored inode in the managed restore directory
serves the original 80 through the formal read-only HTTP application. Write
attempts reject. Missing source, wrong identity, schema, FK violations, truncation
and valid-but-wrong watermark/content are rejected.

C: seven actual controller SIGKILL cuts: copy complete with old worker still
alive, publication intent, post-rename, post-catalog, restore materialization,
delete intent and post-unlink. A live old worker blocks takeover. Formal recovery
keeps/removes exactly the expected known objects/pins; independent stale epoch
and revision attempts and retired-phase updates reject. Portable tests also close
the controller normally while a real copy worker is alive, including a barrier
inside interpreter/atexit shutdown: replacement remains BUSY until process exit.

D: the 64 MiB ext4 loop fills after actual backup admission, producing ENOSPC=28
and SQLITE_FULL=13 rather than a preflight-only refusal. New durable startup
refuses, old usable backup content survives, limited read-only diagnosis works,
and explicit free-space repair permits new backups. A readonly bind mount gives
OS EROFS=30 and SQLite CANTOPEN=14 to an already-running controller; it retires and
rejects another mutation. Removing the fault restores operation. A separate
catalog page-cap FULL=13 also retires the writer until explicit reopen/recovery.
These actual mappings are recorded; no mocked storage errors qualify D.

## Single controlled Linux observations

| Observation | Result | Interpretation |
|---|---:|---|
| Backup, 80 ledger transactions | 28.98 ms | One ordinary trial, includes validation/publication |
| Restore to first successful HTTP query | 36.71 ms | Separate copy plus loopback reader startup; no production switch |
| Controller RSS at B observation | 24,304 KiB | Point reading; process had earlier work, not isolated backup peak |
| Read-only view RSS at B observation | 20,956 KiB | Point reading, not peak |
| Managed logical bytes, backup plus restored copy | 730,341 | Includes control metadata |
| Managed allocated bytes at same point | 741,376 | Filesystem blocks, distinct from logical lengths |

A's writer latency and WAL numbers come from an intentionally held reader;
they are fault-behavior observations, not a normal-performance comparison.
There is no native-vs-VM comparison, speedup claim, outage guarantee, long-run
leak claim or universal RPO/RTO guarantee. The complete raw values stay in JSON.

## Failures, cleanup and limits

Three failed runs remain failed. The earlier pass is retained under its original,
weaker correspondence gate rather than relabelled. All four historical JSON/HTML
receipts preserve their own source maps and observations. First-run D has no full
retained details; it is not claimed passed. See the attempt ledger for individual
causes. A separate distro-SQLite readonly-mapping diagnostic is explicitly not a
qualified product-runtime result.

The current run removed its mount/loop device and owned worker/view processes.
Its dedicated VM and container-data disk were deleted and absence read back.
Preexisting profiles kept their previous status. Local credentials, logs, wheels,
SQLite source/library, images and runtime catalogs are excluded from Git.

This is an exploration core, not a completed operational MVP: no persistent
scheduler/control API, general profiles, supervised reader leases, age retention
or bounded receipt garbage collection yet. Default receipt capacity is 128 and
refuses further work; it is not an endless-service claim. Abrupt power loss, VM
reboot, physical storage behavior and production cutover are untested. A same-disk
backup cannot establish recovery after loss of that disk.
