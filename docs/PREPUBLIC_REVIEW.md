# Pre-publication review

Review parent: `1145702ba65d5ac62a5efc2174d1ff9f14555ee5`. The repository stays
Private with no selected project license. This review covers current runtime and
tests, README/design/evidence boundaries, package contents and tracked Git history.
It does not authorize publication or add product features.

## Application relation defect and repair

A formal backup could publish a `ledger-v1` database whose transaction-item rows
were not associated with actual transactions. Before repair, the canonical
`init_ledger` schema with both children of transaction 1 changed to `seq=NULL`
still passed SQLite's `foreign_key_check`, total count and grouped part checks.
A real Controller/worker backup published count=3. A second real probe rebuilt
`item` without its FK and inserted only nonexistent parents; it also published.
These are actual false acceptances, not merely malformed-report examples.

SQLite permits a NULL child FK; counting rows and checking part shape does not
independently prove parent membership. `inspect()` now uses an anti-join check to
require every child to match an actual `tx.seq`, independently of FK declaration.
The same function is used by snapshot inspection and closed backup/restore
verification. Existing sequence/content, item count/parts, identity, integrity,
FK, hash, deadline and publication checks remain in place.

Two regressions use the formal Controller and actual worker. Both had to fail on
the old implementation; after repair they must receive the specific parent
mismatch refusal, with no published backup or staging leftovers. The core suite
went from 32 tests with two failures to 32 passing. The qualification verifier
also requires the new test IDs, rather than accepting only a larger test count.
This remains a fixed semantic contract, not a general schema certification.

[Sanitized probe/test record](../evidence/prepublic/review.json) explicitly labels
its manual observations. Raw local test data/logs and wheel stay ignored.

## Documentation, scope and publication artifacts

- The current README describes the bounded delivered service. Scheduler, age
  retention, automatic guard/tombstone GC, forced orphan adoption, systemd
  packaging and production database replacement remain deferred.
- Earlier source-bound measurements and failed attempts remain intact. The prior
  reviewed closeout run is retained as `attempt-06.json/html`; it does not qualify
  the new application check. Historical indexes explicitly link to current evidence.
- The quickstart now writes its native test receipt under ignored `results/`.
  The old root-level `results-unit.json` is also ignored, preventing accidental
  upload of ad hoc local output. The tests/tools command requires a source checkout;
  those files are not claimed to be part of the runtime wheel.
- The quickstart explicitly installs its declared build tools and activates its
  venv. Linux instructions persist `LD_LIBRARY_PATH` for subsequent commands,
  matching the qualified library path selected explicitly by the runner. A
  one-command environment prefix is not presented as a persistent setup.
- The rebuilt wheel contains only project Python modules and distribution metadata,
  no data, private settings, VM image, third-party runtime source/binary or license
  declaration. Runtime dependencies remain Python stdlib and external SQLite;
  [third-party terms](THIRD_PARTY.md) are separate from the unselected project license.

## Privacy and history scope

At the reviewed parent, all seven reachable commits / 171 unique blobs
(2,396,323 bytes) were scanned. No candidate private home/temp paths, private/SSH
keys, GitHub/AWS credentials, literal credential assignments, private IPv4 values
or binary artifacts were found. No forbidden results/venv/personal-guidance/data
paths appeared in tracked history. Commit identities use GitHub noreply addresses.
Current candidate files are checked again before commit; raw logs, source data,
`.venv`, wheel/build output and personal AGENTS/settings remain excluded.

This is a targeted pattern scan plus artifact/content review, not proof that
secret scanners can detect every possible sensitive value. No history rewrite,
public visibility change, new collaborator or license grant is performed.

## Evidence interpretation

The repaired package must be rebuilt and installed in a new isolated Linux VM,
with source imports removed and module/library hashes verified. Both platforms
must run identical tests, with the new relation cases present; existing capacity,
reader/orphan faults, 24-cycle resource observation and two normal VM reboots are
repeated. Source fingerprint, JSON/HTML and unit receipts must agree.

RSS remains sampled Linux VM process RSS. It may grow within the predeclared
allowance; retained metadata also grows. There is no comparative speedup, peak
memory or indefinite-longevity claim. The earlier composite resource failure
without samples remains unresolved, not reclassified as a harmless race. Normal
reboot recovery is checked before service startup and is distinct from systemd
autostart, sudden power loss, physical-device behavior and boot zero-gap. None of
the latter unmeasured capabilities is declared passed.


## Actual repaired-package outcome

Installed-package run `21c52afcecce99d5` passed the same 83 test IDs on native
macOS and Linux (zero failures/errors/skips), including both new formal-backup
relation cases. Ten baseline VM cases, four closeout cases and two normal VM
reboots passed. Source fingerprint is
`2e021cf36ce897de501d1325879dccefdf42e07f3ec394a5f5390740acea4478`.
63 report corruption controls were rejected; JSON and HTML match, and the new
wheel's `keepweft/data.py` hash matches the frozen source/installed module.

The 24-cycle observation lasted 124.69 seconds. Controller RSS was 21,096 KiB
initially, 28,424 KiB after the declared warmup and 30,244 KiB maximum/end
(+1,820 KiB after warmup, within 4,096 KiB). All raw and quiescent FD counts were
7. There were zero remaining children, active restores, reader metadata or pins
at cycle boundaries. Expected retained metadata grew; this is not a plateau or
long-term memory bound. Both normal reboots preserved recovery witnesses before
service startup, and old authority rejected without mutation. VM/data disk and
product-process cleanup passed; preexisting profiles/statuses were unchanged.

The review's local targeted history/artifact scan found no private-information
candidate; project license remains unselected. No remote CI rerun, abrupt-power-loss,
autostart, physical-storage or zero-gap qualification is claimed. The historical
resource failure with missing samples remains explicitly unresolved.
