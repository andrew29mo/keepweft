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

## Current outcome

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
