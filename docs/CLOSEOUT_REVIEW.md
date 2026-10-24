# Closeout review and evidence repair

Two independent read-only reviewers examined commit `04dcb7d` against the formal
controller/service/reader, installed-wheel provenance, raw ignored VM logs,
published receipts and documentation. Their findings concern validation coverage,
not a reproduced product corruption or a false original 124-second measurement.
Model agreement is not qualification: only executable observations and the new
installed-package run qualify the repairs.

## P2: capacity witness was narrower than its claim

The old capacity case compared only each `db.sqlite` hash and receipt **count**,
then queried an already-running restored copy. A reviewer wrapped the real
service submit response and corrupted every published `manifest.json` after
capacity refusal. Both receipt and logical-capacity cases still passed (four and
three corrupt manifests respectively), reporting preserved inventory and safe
stop/release. This is a confirmed observer gap; the formal product was not found
to perform that corruption itself.

The new witness compares all backup directory identities and file contents,
complete authority/operation/backup/restore/reader/request/namespace catalog rows,
and complete service status, excluding only shared filesystem free space. Both
witness hashes are retained; raw catalog data containing local paths/reader nonce
is not exported. Portable tests inject manifest-file, backup-catalog and
request-content changes after refusal for **both** capacity modes. Each must fail
at the exact owned-state comparison, rather than at unrelated cleanup.

## P2: invalid resource observations could pass

The old resource checker verified stable PID/FD values and upper bounds but did
not first validate numeric types/ranges. A reviewer changed copied JSON to
negative PID/FD/RSS/logical/catalog bytes or zero RSS, and both sample/full-report
verification accepted it. Last-sample NaN RSS also passed comparison, although
strict JSON serialization separately refused NaN. The original raw values are
positive, plausible and match the published receipt; they were not disproven.

Every sampled field now requires an exact integer type (bool excluded) and its
legal range before cross-sample checks. PID, RSS, FD and catalog size must be
positive; other counts/bytes are nonnegative, and logical bytes include catalog
bytes. Negative, zero, bool and nonfinite controls challenge the repaired checker.
The original four-cycle warmup, 4,096-KiB RSS allowance, 24 cycles, five-second
reader dwell and no-restart conditions remain unchanged.

## Independent authority coverage

The old reboot test submitted a token whose epoch **and** revision were stale.
That rejects safely in the actual implementation but cannot isolate the service
reader's epoch check. Existing direct-core tests independently covered the two
dimensions; the new formal-service checks do so too: old epoch/current revision,
and current epoch/old revision. They require the explicit authority rejection and
unchanged catalog/status and backup-file witness. Both reboot cases and the documented workflow
exercise these checks. A RELEASED instance's unrelated refusal cannot satisfy the
expected explicit-authority error.

## Retained evidence and boundaries

`evidence/closeout/attempt-03.json/html` preserve the original run
`6cd302fed9c0ea83` (124.04 seconds), byte-for-byte. Its values, installed module
hashes and reboot witnesses remain valid historical observations, but it does not
qualify the added guards. Earlier short/failed attempts also remain retained.
[Current evidence](../evidence/closeout/README.md) records the separate new source
fingerprint, identical portable tests, actual VM run, rejected report mutations,
cleanup and measurements. The two-minute observation is bounded and sampled;
metadata is retained and grows, and RSS need not be flat.

The shared-free-space test correction still ignores only `statvfs` free bytes
for the whole host filesystem. Managed status, logical/allocated bytes and
file-content hashes remain checked; the separate real-file mutation control
still rejects an owned-state change. No test timeout or resource threshold was
relaxed in this review.

Both normal reboot cases kill the controller before shutdown, preserve catalog
and copy witnesses, require a different kernel boot ID, and compare the untouched
catalog **after boot before starting the formal service**. Neither is a claim of
systemd autostart, boot zero-gap or sudden-power-loss recovery. Software receipt
and logical-budget rejection are not new physical ENOSPC/SQLITE_FULL evidence.
No new product features or license grant are introduced; repository stays Private.

## VM setup cleanup finding during rerun

The first review rerun used an overly long profile name. Lima rejected its
107-byte temporary SSH socket path (macOS maximum is 104), before a VM existed,
but Colima had already created an empty sparse data disk. Colima deletion alone
did not remove that detached disk. The failed receipt remains unchanged, including
`data_disk_removed=false`; the owned empty disk was subsequently removed through
Lima's normal disk-delete command, and absence was checked separately. No other
profile/disk was removed. This was not a product-test pass.

The runner now checks the full temporary socket path before creating resources.
A regression requires a too-long name to refuse without creating its target
path. Cleanup also attempts normal Lima disk deletion of this exact owned name
if Colima leaves it behind; it does not force deletion of an in-use disk. The
fresh-profile/initial-disk-absence proofs still gate ownership. Unexpected cleanup
stages/failures remain failed qualification rather than a silently repaired pass.
The final review run uses a shorter new name and a fresh output directory.

## Resource rerun failure and missing diagnostics

The next actual run passed 81 tests on each platform and all 10 baseline Linux
cases, then failed the composite `FD/child/pin/reader leak` assertion after about
125 seconds. Its original receipt remains `attempt-05.json/html`, and its VM/data
disk were removed. The old sustained-case function returned samples only after
validation, so it lost the offending observations on this failure. The exact
failed field/cause cannot be recovered; it is **not** relabelled as a proven RPC
race, a product leak, or a pass.

A status response can reach the client just before the server closes that RPC's
accepted socket. That is a plausible observation race, not a demonstrated cause
of attempt 05. The sampler now records actual FD targets and relevant Unix inode
flags (including unknown entries), so listener classification can be recomputed.
It requires two consecutive same counts and no owned non-listener sockets within
250 ms. Unknown socket inodes stay pending. It does not take a minimum or wait
for a preferred count. Final FD counts must still equal cycle 0 on every cycle;
a persistent extra regular-file FD fails, even with consistent raw witnesses.
RSS, four-cycle warmup, 4,096-KiB allowance, cycles and dwell are unchanged.

Per-cycle observations are atomically saved before final validation, including on
failure. The runner fetches available failed case/sample artifacts before deleting
the VM. Controls distinguish a drained transient RPC socket from a persistent FD
increase, and reject inconsistent or pending socket witnesses. This improves the
observability contract; a later pass cannot explain the old unobserved failure or
prove all future executions safe.

## New qualification outcome

Run `9933e02c1ba18673` qualifies the current source fingerprint recorded in the
latest receipt. Native macOS and installed Linux passed the same 81 test IDs,
zero skips/errors/failures; 10 baseline VM cases, four closeout cases and two
normal VM reboots passed. The 24-cycle trial lasted 124.16 seconds, all raw and
quiet FD observations were 7, and sampled RSS rose 916 KiB after the unchanged
four-cycle warmup (within 4,096 KiB). Both dimensions of stale reader authority
rejected independently without owned-state changes. Sixty-two report corruptions
were rejected. VM/data disk and product-process cleanup passed.

Both reviewers independently cross-checked this new actual receipt, raw logs,
source fingerprint and HTML correspondence. They did not themselves rerun the
VM; the primary agent performed the installed-package execution. This new pass
supports the new observation contract and cannot recover attempt 05's missing
samples or resolve its unknown cause. Its failed status and limitation remain.
