# Bounded closeout evidence

The current receipt is `latest.json`, with exactly corresponding `latest.html`.
It qualifies only the bounded local `ledger-v1` MVP described in
[the operator and closeout document](../../docs/CLOSEOUT.md).

`attempt-01.json/html` retain the original 24-cycle trial (2.679 seconds) and two
normal VM reboots, byte-for-byte. It passed its then-current contract, but was
superseded for sustained-operation evidence: repeating operations quickly is not
a meaningful dwell trial. Do not run the stricter current verifier and relabel
that older receipt as current. `development.json` is a manually written sanitized
account of test-harness mistakes and the strengthened observation requirement;
it is not raw VM evidence. Raw private logs and wheel/VM artifacts remain ignored.

`attempt-02.json/html` retain a failed native gate (one failure among 78 tests):
a stale-operation test incorrectly compared shared whole-filesystem free bytes.
The dedicated native receipt is also retained; no Linux product/reboot pass is
inferred from that failed run. The VM and data disk were deleted. The corrected
observer retains all owned state and file hashes, excluding only shared free
space; a separate negative control still detects real file mutation.

The final trial declares 24 cycles with at least five seconds of actual live
reader dwell and two valid queries per cycle, one controller PID, no restarts,
and resource samples after every cycle. Expected retained metadata growth is
explicitly reported; RSS samples are not continuous peaks or long-term proof.
Software receipt and logical-budget rejection are separate from physical-disk
faults; older physical-fault receipts remain historical.

Normal VM reboot is separate from sudden power loss. Both current reboot cases
must preserve identical catalog bytes/rows and copy hash after boot **before**
formal controller recovery. The controller is SIGKILLed before normal reboot,
preventing its graceful shutdown handler from performing the recovery for us.
The reader/process reset is a real kernel boot, evidenced by changed boot IDs.
No automatic systemd service installation or full boot protection is claimed.

## Previous outcome (superseded after review)

Run `6cd302fed9c0ea83`, source fingerprint
`e569a10c87b30e6f5edfe2d7d58ebcf1b3523e672629a5339bddd6250f589249`:
79 identical portable tests per platform (no failures/errors/skips), 10 repeated
Linux phase-two cases, four added closeout cases, and two normal guest reboots.
All stages exited zero within their bounds. Nineteen new plus 29 baseline report
corruptions were rejected. The VM and its owned data disk were deleted, product
process cleanup passed, and existing profiles/statuses remained unchanged.

| Linux VM observation | Start | Cycle 4 warmup | Maximum | End |
|---|---:|---:|---:|---:|
| Controller sampled RSS (KiB) | 21,088 | 28,488 | 29,396 | 29,396 |
| Quiescent controller FDs | 7 | 7 | 7 | 7 |
| Managed logical bytes | 57,344 | 427,814 | 490,714 | 490,714 |
| Catalog bytes | 57,344 | 57,344 | 118,784 | 118,784 |

The 24-cycle observation lasted 124.04 seconds, without a controller restart.
Post-warmup sampled RSS increased 908 KiB; it did not remain constant. Every cycle
ended with zero children, active restores, pins and reader metadata. The end
contains 48 operation rows, 24 request/backup/restore rows each, and 48 files in
the guard directory (24 fixed guards plus 24 ready hints). Logical/allocated bytes
were 490,714 / 606,208 at the end; service log bytes remained zero. This expected
retention is not a GC or indefinite-operation pass. The source DB/WAL is outside
the managed-store budget. No host/native RSS comparison is made.

Both reboot cases changed the kernel boot ID and preserved identical catalog
hash/rows plus copy content before starting the service after boot. SERVING was
reconciled to READY, queried again with count=40 and safely released; RELEASING
was completed to RELEASED. Both rejected old authority and ended with pin=0.
The service is explicitly started by the test after the pre-recovery witness;
this does not qualify systemd autostart. Sudden power loss, boot zero-gap,
physical-storage behavior and long-term guard/tombstone GC remain untested.


## Review qualification

`attempt-03.json/html` preserve the 124.04-second run above unchanged. Review
found capacity-witness and numeric-validation gaps, plus confounded stale-token
coverage; it did not disprove the original measurements. The latest schema adds
full-state refusal witnesses, typed resource checks and independent service
epoch/revision rejection. [Review details](../../docs/CLOSEOUT_REVIEW.md).

`attempt-04.json/html` retain a VM setup failure due to a too-long Lima socket
path. The detached empty data disk was removed afterwards using the formal Lima
command; the original failed cleanup flag is not overwritten. Separate cleanup
observations are labelled manual. `attempt-05.json/html` retain a subsequent
81-test/platform run that failed the composite FD/child/pin/reader check. Its
missing offending samples prevent root-cause attribution. The sanitized failure
summary records this uncertainty, and the new sampler retains all raw FD/socket
observations before validation. See the review document; no failed run is promoted.


## Previous reviewed outcome (before application-relation repair)

Run `9933e02c1ba18673`, source fingerprint
`cb3e6cf2614a571abe25e7c5e9a244296d5baf90bd26126e1f3a6c03ffa45ef9`:
81 identical portable tests on each platform, no failures/errors/skips. Ten
baseline Linux cases, four closeout cases and two normal VM reboots passed;
33 new plus 29 baseline report corruptions were rejected, also under Python -O.
The installed wheel's product modules are unchanged by this review; only tests,
qualification/observation tools and documentation changed. Source module/library
hashes and raw logs were independently cross-checked against the exported fields.

| Prior Linux VM observation | Start | Cycle 4 warmup | Maximum | End |
|---|---:|---:|---:|---:|
| Sampled controller RSS (KiB) | 21,088 | 28,424 | 29,340 | 29,340 |
| Quiescent controller FDs | 7 | 7 | 7 | 7 |
| Managed logical bytes | 57,344 | 427,816 | 490,716 | 490,716 |
| Allocated bytes | 61,440 | 462,848 | 606,208 | 606,208 |
| Catalog bytes | 57,344 | 57,344 | 118,784 | 118,784 |

24 cycles lasted 124.16 seconds, with five-second live-reader dwell and no
controller restart. The post-warmup sampled RSS increase was 916 KiB, below the
unchanged 4,096-KiB allowance; RSS did not remain constant. All raw and quiescent
FD samples were 7, classified from retained `/proc` targets/Unix flags. This run
observed no pending non-listener socket; it does not prove the cause of the old
failed run. The new observation protocol requires two consecutive quiet counts
within 250 ms and still compares every cycle with cycle 0; it takes no minimum.

Every cycle ended with zero children, active restores, pins and reader metadata.
Retained rows/guards grow as declared: 48 operation rows, 24 backup/request/restore
rows each, and 48 guard-directory files (24 locks plus 24 ready hints) at the end.
Service-log bytes were zero. Source DB/WAL is outside managed accounting. These
are bounded VM samples, not continuous peaks, native comparisons or long-term GC.

Both capacity cases now compare all backup files, complete catalog rows and
status (only shared filesystem free bytes excluded), with matching pre/post
witness hashes. Both reboot cases preserved identical catalog bytes/rows and copy
hash after boot before service startup, then recovered READY / RELEASED correctly.
Old epoch/current revision and current epoch/old revision each explicitly refused
without changing owned catalog/status/backup state. Final pin count was zero.
VM/data disk deletion and product-process cleanup passed; preexisting profiles
and their statuses were unchanged. No systemd-autostart, sudden-power-loss,
boot-zero-gap or physical-storage claim is made.


## Current pre-publication outcome

Run `21c52afcecce99d5`, source fingerprint
`2e021cf36ce897de501d1325879dccefdf42e07f3ec394a5f5390740acea4478`:
83 identical tests on each platform, zero failures/errors/skips; 10 baseline Linux
cases, four closeout cases and two normal VM reboots passed. Thirty-four closeout
plus 29 baseline report corruptions were rejected. The installed wheel includes
the parent/item relation repair and its required formal-backup negative tests;
module/library hashes match. The previous reviewed run is preserved byte-for-byte
as `attempt-06.json/html` and does not qualify this changed product module.

| Current Linux VM observation | Start | Cycle 4 warmup | Maximum | End |
|---|---:|---:|---:|---:|
| Sampled controller RSS (KiB) | 21,096 | 28,424 | 30,244 | 30,244 |
| Quiescent controller FDs | 7 | 7 | 7 | 7 |
| Managed logical bytes | 57,344 | 427,810 | 490,714 | 490,714 |
| Allocated bytes | 57,344 | 458,752 | 606,208 | 606,208 |
| Catalog bytes | 57,344 | 57,344 | 118,784 | 118,784 |

The 24-cycle observation lasted 124.69 seconds without a controller restart.
Post-warmup sampled RSS increased 1,820 KiB within the unchanged 4,096-KiB
allowance; all raw and quiescent FD counts were 7. Every cycle ended with zero
children, active restores, pins and reader metadata; expected retained rows and
guards grow. No continuous-peak, flat-memory or long-term-GC claim follows.
Capacity before/after full-state hashes matched. Both normal reboots preserved
catalog rows/hash and copy content before controller startup, then reconciled
READY / RELEASED and independently rejected old epoch/revision without mutation.
VM/data disk/product-process cleanup passed; existing profiles/statuses unchanged.

The pre-publication review repaired actual false acceptance of NULL/orphan item
parents. [Review](../../docs/PREPUBLIC_REVIEW.md) and [sanitized pre-fix probes](../prepublic/review.json)
separate this defect from prior observer gaps. The older unexplained composite
resource failure remains unresolved; it was not promoted to a pass. No systemd
autostart, sudden-power-loss, boot-zero-gap or physical-storage capability is
newly qualified. At that qualification, no project license had been selected.
The project is now [MIT licensed](../../LICENSE) and remains Private;
[adoption checks](../../docs/LICENSE_ADOPTION.md) explain the metadata-only
source-fingerprint change without rewriting these historical receipts.
