# Bounded MVP closeout

The delivery boundary is a local, trusted-same-UID, single-source `ledger-v1`
backup request service with one validated restored copy and one managed read-only
reader. It is a bounded MVP, not the entire earlier service roadmap. Scheduling,
age retention, automatic guard/tombstone GC, systemd packaging and live production
replacement are deferred. The repository is Public and [MIT licensed](../LICENSE).

## Clean Linux installation used by qualification

The runner creates a fresh 2-CPU / 3-GiB / 15-GiB Colima Linux VM with no host
mounts and first checks that `python3 -I` cannot import Keepweft. These commands
are for the disposable Ubuntu VM only; do not override a shared host's system
Python. Copy a locally built wheel, the qualification tools/tests, and the pinned
SQLite build helper into `/opt/keepweft` first. The runner performs this transfer
and checks the wheel's modules against the frozen source manifest.

```sh
sudo apt-get update -qq
sudo apt-get install -y python3-pip gcc libc6-dev e2fsprogs util-linux
sudo python3 /opt/keepweft/source/tools/build_sqlite.py --root /opt/keepweft/runtime
sudo python3 -I -c 'import importlib.util; assert importlib.util.find_spec("keepweft") is None'
sudo python3 -m pip install --break-system-packages --no-deps --no-index \
  /opt/keepweft/keepweft-0.1.0-py3-none-any.whl
sudo mv /opt/keepweft/source/keepweft /opt/keepweft/retired-product-source
export LD_LIBRARY_PATH=/opt/keepweft/runtime
python3 -I -m keepweft.cli runtime
```

Keep this environment in each shell that runs the service/client; a prefix on
one command does not configure later shells. The qualification runner explicitly
sets the same library path for each guest command.

The build helper verifies official SQLite source before compiling. Actual loaded
library mapping/hash and installed module hashes are independently checked. No
third-party binaries/sources or VM images are published. Root is used inside the
isolated qualification VM for existing filesystem-fault cases; ordinary service
operation uses an owner-only store and does not require root.

## Complete operator sequence

Use an empty canonical absolute workspace outside the source checkout. Run the
following with the qualified Python/SQLite environment above. `init-source` is
only a demonstration data generator; it must never overwrite a real database.

```sh
python3 -m keepweft.cli init-source --source /absolute/live.sqlite --count 40
# Save the returned result.uuid as SOURCE_UUID.
python3 -m keepweft.service --root /absolute/store \
  --source /absolute/live.sqlite --uuid SOURCE_UUID
# Keep this foreground service running; use another terminal for the next steps.
python3 -m keepweft.client prepare --root /absolute/store --envelope /absolute/request.json
python3 -m keepweft.client submit --root /absolute/store --envelope /absolute/request.json
python3 -m keepweft.client lookup --root /absolute/store --envelope /absolute/request.json
# Repeat lookup until AVAILABLE, or stop and inspect a FAILED/CANCELLED result.
```

Use the returned `result_id` as BACKUP_ID. Before **each** mutation, fetch status
and save its exact `result.inventory.token` object as an external token file:

```sh
python3 -m keepweft.client status --root /absolute/store > /absolute/status.json
python3 -c 'import json; s=json.load(open("/absolute/status.json")); assert s["ok"]; json.dump(s["result"]["inventory"]["token"],open("/absolute/token.json","w"))'
python3 -m keepweft.client reader --root /absolute/store \
  --command restore --id BACKUP_ID --token /absolute/token.json
# Save returned restored instance id as RESTORE_ID, refresh token from status.
python3 -m keepweft.client reader --root /absolute/store \
  --command start --id RESTORE_ID --token /absolute/token.json
python3 -m keepweft.client reader --root /absolute/store --command query --id RESTORE_ID
# Refresh token from status before stop, then again before release.
python3 -m keepweft.client reader --root /absolute/store \
  --command stop --id RESTORE_ID --token /absolute/token.json
# Require exit_proven=true. A timeout/busy orphan is not successful stop.
python3 -m keepweft.client reader --root /absolute/store \
  --command release --id RESTORE_ID --token /absolute/token.json
python3 -m keepweft.client status --root /absolute/store
# Require RELEASED, pin=0; then stop foreground controller with SIGTERM/Ctrl-C.
```

A stale response is not permission to mint a fresh retry. Keep exact backup
envelopes; inspect state before deciding a new reader mutation. The executable
`documented_cli` scenario runs the same CLI commands, explicitly parses JSON,
refreshes tokens and checks their exit statuses. Other fault/resource scenarios
call the same formal Unix service API, not a replacement controller/backend.

If the controller crashes, restart the same installed service and registered
store. A surviving reader remains ORPHAN_BUSY, keeps its pin/copy and may still
answer queries. Do not kill a persisted PID: it may have been reused. There is no
forced adoption/termination API. Let the independently supervised reader exit,
then use stop to establish a free guard before release. If its identity/exit is
unknown, preserve the store and investigate offline. Gracefully stopping the
controller alone deliberately leaves readers alive; stop/release first for a
fully stopped deployment.

## Declared closeout challenges

- Two separate policy capacity tests: four request receipts, and a 1,300,000-byte
  logical budget with 262,144-byte artifact cap / 65,536-byte headroom. They fill
  the declared policies using actual backups while a reader remains live. The
  rejected request must not prune backups, change their hashes or consume a
  receipt; query/stop/release must still work. The refusal witness compares all
  backup files/manifests, full catalog rows and status (only global free space is
  excluded); only the two witness hashes are exported and must match. Corruption
  controls modify manifest, backup state and receipt contents for both modes.
  These are software admission
  limits, not new physical ENOSPC or SQLITE_FULL qualification.
- Exactly 24 backup/restore/start/query/stop/release cycles, 40 source entries,
  at least 5 seconds of reader dwell with queries on both sides per cycle (at
  least 120 seconds total),
  one unchanged controller PID and no restarts. Sample Linux process RSS, FD and
  child counts after each complete cycle. After status RPC, FD observation must
  reach two consecutive equal counts with no owned non-listener socket within
  250 ms; all raw FD targets/socket flags are retained. It does not select a
  minimum count; every quiescent count must still equal cycle 0. Unknown socket
  inodes remain pending. Every cycle is atomically saved before final validation
  so a later failure keeps its observations. From cycle 4 onward, maximum sampled
  RSS may be at most 4,096 KiB above cycle-4 RSS. Require stable quiescent FDs,
  zero remaining children/active restores/pins/readers, zero service-log bytes,
  exact expected metadata counts, logical bytes <=64 MiB and catalog <=8 MiB.
  Numeric fields are checked for exact integer types and legal ranges before
  bounds (PID/RSS/FD/catalog positive; counts/other bytes nonnegative).
  Thresholds are declared before execution; sampled RSS is not a continuous peak.
- Retained metadata is **expected to grow**: each cycle keeps two operation rows,
  one backup/restore/request row and two guard-directory files (fixed lock + ready
  hint). Backup files follow keep=2. No claim of a memory/disk plateau, unlimited
  operation or long-term GC follows from a short bounded run. Catalog/receipt
  limits can eventually require stopping and offline reconciliation; no supported
  online guard/tombstone reset exists. Never delete guards to reclaim space.
- Two **normal guest OS reboots**, one with a serving reader and one at a durable
  RELEASING intent. Before reboot, SIGKILL the controller to prevent a graceful
  shutdown cleanup from serving as recovery evidence. Persist catalog hash/rows,
  pin=1 and copy hash. After boot, before launching any controller, require a new
  kernel boot ID and byte-identical catalog plus unchanged copy. Only then start
  the installed formal service, check READY or RELEASED, reject old authority,
  reject old epoch/current revision and current epoch/old revision separately,
  require unchanged catalog/status and backup files, query the recovered READY copy and release
  exactly once. The intent case uses
  an explicit scheduling barrier; the serving case has no barriers.

The first 10 phase-two VM scenarios are repeated against the current installed
package, alongside identical portable tests on macOS/Linux. Their nested
`vm_reboot_tested=false` flag describes that historical case group only; the
closeout top-level limits and separate reboot receipts describe the two new
normal reboots. Neither group qualifies sudden power loss or boot zero-gap.

## Reproduce and inspect

```sh
.venv/bin/python -m pip wheel --no-deps --no-build-isolation --wheel-dir results/closeout-wheel .
.venv/bin/python -m tools.closeout_validate \
  --colima-home /absolute/dedicated-colima-home \
  --toolchain /absolute/colima-toolchain/bin \
  --profile keepweft-exp-closeout-UNIQUE \
  --wheel results/closeout-wheel/keepweft-0.1.0-py3-none-any.whl \
  --output results/closeout-UNIQUE
```

The profile name and Colima home must also fit the macOS temporary SSH socket
path limit (<104 bytes); overly long paths refuse before any VM resources are
created. Fresh profile, absent retained data disk and fresh output directory are required. Each stage
has a hard harness bound; failures, timeouts, missing observations and cleanup
errors remain failures. Expected SSH outages are recorded as reboot transport
polls, not relabelled test passes; success requires a different observed boot ID
and all post-boot assertions. Raw logs stay ignored. Sanitized JSON and HTML must
match byte-for-byte after rendering and carry source/runtime fingerprints.

[Current evidence](../evidence/closeout/README.md) records actual outcomes and any
superseded attempts. A passing bounded closeout supports this scoped local MVP;
it does not certify arbitrary schemas, physical storage durability, production
cutover, long-term guard GC, abrupt power loss or continuous boot protection.

[Closeout review and repaired counterexamples](CLOSEOUT_REVIEW.md) distinguish
validation gaps from actual product failures and retain the original measurements.
