# Reproduction and interpretation

## Environment and prerequisites

Use macOS, Python >=3.12 with a qualified linked SQLite, Colima/Lima and network
access to Ubuntu packages and the official SQLite archive. The runner requires a
fresh `keepweft-exp-*` profile with no preexisting rootfs/container-data disk,
creates 2 CPUs / 3 GiB / 15 GiB and `--mount none`, and deletes exactly that owned
profile and data disk on success or failure. Existing profiles are not started,
stopped or deleted. Never execute `tools.explore` directly on a host/production
machine: its finite ext4 loop/full/readonly faults are for the isolated VM only.

Build a pure-Python wheel, then run:

```sh
.venv/bin/python -m pip wheel --no-deps --wheel-dir results/wheel .
.venv/bin/python -m tools.validate \
  --colima-home /absolute/path/to/dedicated-colima-home \
  --toolchain /absolute/path/to/colima-and-lima/bin \
  --profile keepweft-exp-unique-name \
  --wheel results/wheel/keepweft-0.1.0-py3-none-any.whl \
  --output results/new-exploration
```

Use a fresh output directory; old failed receipts must not be overwritten.
Source manifest includes production modules, tools, tests and pyproject. The
wheel's module hashes must match. Both platform unit receipts must list identical
test IDs and source fingerprint, with zero skips/errors/failures.

The dedicated Ubuntu VM installs the wheel with system-Python pip's explicit
`--break-system-packages` override; this is not a recommendation for a shared
host. The checkout product directory is moved out of import reach before Linux
tests or probes. Both the installed module hashes/location and actual loaded
SQLite shared library are recorded. No product callbacks are replaced by fake
backup/recovery implementations. Test barriers only control scheduling.

The official SQLite amalgamation is downloaded and sqlite3.c SHA3-256 checked
against the release hash embedded in `tools/build_sqlite.py`. Runtime 3.54.1 is
built with the recorded compiler/flags, selected through LD_LIBRARY_PATH, and its
actual mapping is verified in `/proc/self/maps`. Upstream source and library stay
inside the disposable VM. Native SQLite is recorded separately.

## Four probes

A uses a real uncommitted transaction while a worker establishes its read
snapshot. A test-only barrier then allows 32 additional committed transactions
before copying resumes. The backup must contain the exact earlier 192 committed
sequences, while the source contains 224. This barrier deliberately holds the
reader: its 32 writer latency samples and WAL growth demonstrate behavior under
that controlled read lifetime, not normal production backup throughput. Separate
cancel and timeout commands must fail and reap the actual worker before staging
cleanup. Uninterruptible kernel I/O is not injected.

B runs an ordinary uninstrumented backup, advances the live source to 81 entries,
then restores the 80-entry snapshot to a separate inode in the managed restore
directory. This challenges accidental fallback to the source or backup path. The
formal fixed HTTP application must answer from the restored database. RTO here
means restore request through first successful loopback HTTP response, including
reader startup; it is not production cutover RTO. Negative cases corrupt schema,
identity, content and SQLite bytes. Resource values are point Linux `/proc` RSS,
not continuous peaks. Logical file lengths, allocated blocks and filesystem free
space are separate fields; no native/VM performance comparison is claimed.

C kills real CLI controllers at seven named cut points. The copy-complete barrier
intentionally leaves the old worker holding a writable handle; takeover must be
BUSY until that worker exits. Only formal `Controller.recover()` reconciles the
persisted state. Other cases distinguish pre/post rename and catalog commit,
interrupted restore pins and pre/post unlink. Both stale-token dimensions are
submitted separately using the current other dimension. Direct retired-attempt
phase probes challenge the internal lifecycle fence; this is not a network API.

D uses a 64 MiB ext4 loop filesystem. External fault filler is outside the managed
store but on that filesystem, and fills it *after* admission/snapshot. Thus the
probe challenges actual I/O failure, not just preflight refusal. It also applies a readonly bind mount over the managed store while the formal
controller is already running and imposes actual SQLITE_FULL through the catalog's page cap. The
SQLite cap injection is connection-local; explicit close/reopen reapplies the
registered catalog policy and reconciles interrupted attempts. This does not
qualify an automatically repaired corrupt catalog. Linux rejects whole-filesystem
readonly remounts with open writable descriptors; the readonly bind view instead
faults new journal/path writes. The probe independently observes EROFS=30. SQLite
may map journal creation failure to CANTOPEN=14 rather than READONLY=8; the
receipt records its actual code and requires controller retirement, not one
particular textual error message. Read-only diagnosis does not
create a new epoch or claim readiness. Fault filler, mount and loop devices are
removed; remaining paths/images disappear with the owned VM.

## Reporting and limits

`tools.report.verify` rejects absent/reordered/failed/timed-out stages, mismatched
installed sources/runtime, incomplete cases, false success, confounded stale
tokens, failed cleanup and untested power-loss claims. Mutation controls test the
reporter, not the product. Optimized Python must still reject corrupt reports;
test drivers themselves refuse `-O`. HTML embeds the complete escaped JSON and
must correspond exactly to the receipt. Local logs and failed VM diagnostics stay
under ignored results; sanitized receipts/failure summaries are retained.

A failed cleanup remains a failed run even if earlier probes passed. First-run
SQLite context-manager misuse left file handles open and blocked unmount; the
fixed core explicitly closes read connections on both success and failure.
No failed attempt is retroactively promoted. A later passing run had incomplete
ENOSPC error JSON mask the real SQLite error; the revised pipe-first failure
channel preserves it, and a stronger final gate rejects that weaker behavior.
Another failed injection tried a whole-filesystem readonly remount with an open
writer, then a readonly test incorrectly demanded only READONLY=8. A separate
short-lived diagnostic observed EROFS=30/CANTOPEN=14; this is labelled diagnostic
evidence, not a qualified product runtime. The final installed-core run must
repeat all four probes with the revised actual-storage-error contract.

These probes do not establish abrupt power-loss or VM-reboot recovery, hardware
persistence, hard process-cleanup deadlines for stuck I/O, hostile same-UID
isolation, long-term receipt capacity, arbitrary-schema recovery or production
service cutover. Correctness of the fixed ledger profile is not evidence of
correctness for all applications using SQLite.
