# Guarded reader review and repair

Two independent read-only reviews inspected the lifecycle source/diff and the
formal tests, installed-package receipts, report verifier and documentation.
Runtime tests, rather than reviewer agreement, establish the observations below.
This review does not establish VM reboot, power-loss or long-term GC correctness.

## Findings

### Inherited idle HTTP connection could monopolize the managed reader

The existing single-thread HTTP application had no accepted-connection read
inactivity limit. A local unauthenticated connection could send an incomplete
request header and hold the reader before `do_GET` authenticated the nonce.
Queries timed out until that client disconnected. This was inherited by the new
managed reader, not a newly introduced deletion/unpin failure.

The regression uses the actual formal service and reader. It sends an incomplete
unauthenticated header and requires server EOF **before the test closes the
socket**, then queries the original 40-entry snapshot and completes stop/release.
It failed against the previous implementation with an actual socket timeout.
The handler now has a 0.5-second socket inactivity limit and the regression passes.
This is not a total request deadline, bounded-concurrency server or DoS guarantee;
continuous slow input or repeated local connections can still interfere.

### Readiness-deadline cleanup was not independently proved

The earlier timeout case checked the error/pin/state, then called stop. That stop
could terminate a child which startup cleanup had failed to terminate. Thus the
old test did not independently support its description of a reaped startup child.
An in-memory no-op `Popen.kill` mutation in the service still passed that old case.
No source change is needed to expose this evidence gap.

The corrected case observes two facts **before any stop**: a separate-open-FD
exclusive guard is available, and the previously observed owned PID is absent.
The parent remains alive, so a zombie/unreaped PID does not satisfy the assertion.
The same no-op-kill mutation now fails at those observations, before later stop
or test cleanup can repair it. The crash/orphan branch records these deadline
proofs as null; it does not pretend to reap a child owned by a dead controller.

A separate unit test runs the formal startup and actual reader process while
injecting only an ineffective kill. It confirms the child remains live, release
refuses, and copy/pin/STOP_REQUESTED remain. A later real stop proves exit before
release. This injection is not a real uninterruptible-kernel-task experiment.

## Scope of the review result

No live-reader deletion or premature pin decrement was reproduced within this
scope. Instance guard inheritance, separate global-writer takeover, stop timeout,
stale epoch/revision rejection, release parent sync and repair remain challenged
by formal-process tests. This statement is bounded by the tested faults, not a
claim of universal safety.

The native pre-repair full suite passed 72 tests, illustrating why passing the
old suite did not rule out either finding. The strengthened pre-fix reader suite
had 17 tests with one actual idle-header timeout; after repair all 17 passed.
A manually sanitized [review baseline](../evidence/phase2/review-baseline.json)
records these facts without uploading raw personal paths or logs. It is not a VM
qualification receipt. Current full native/installed-Linux receipts, actual VM
scenarios and matching JSON/HTML are retained in [phase-two evidence](../evidence/phase2/README.md).
The previous final receipt is preserved as attempt 04 with its original contract.

Timings include the test client's preliminary status/token RPC and receipt of the
start response after the real readiness query. RSS is a point observation; it is
not peak memory or long-run growth qualification. Raw test logs, wheels, stores
and VM images remain ignored. No project license has been selected; repository
visibility remains Private.
