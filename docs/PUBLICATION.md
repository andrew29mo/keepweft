# Public repository verification

On 2026-10-24, `andrew29mo/keepweft` was changed to Public at the owner's explicit
request. GitHub identifies the license as MIT. README, LICENSE and both platform
receipts were read without authentication and matched the committed bytes.
Current workflow documents now say Public; dated pre-publication observations
and source-bound raw evidence remain historical records.

## Validation evidence

The existing closeout verifier passed. Native macOS and isolated Linux receipts
contain the same 83 passing test IDs with zero failures/errors/skips. All 22
retained JSON/HTML pairs match. Re-running the report controls rejected 34
closeout and 29 baseline corruptions. A targeted pattern scan of 201 reachable
historical blobs found no private home/temp paths or credential-pattern candidates;
this is not proof that every possible secret can be detected.

No runtime, test or validation-tool code changed for publication. The MIT adoption
changed only `pyproject.toml` in the qualification manifest; the
[adoption checks](LICENSE_ADOPTION.md) explain its different fingerprint and
record the subsequent 83-test native pass and package verification. Existing
Linux VM measurements/reboots were not rerun or relabelled for publication.

## Repository security

The owner authorized the following settings, which were applied and read back:

- Secret scanning and push protection enabled.
- Dependabot vulnerability alerts and security updates enabled; weekly pip
  version checks configured for build metadata. No extra runtime Python package
  dependencies are declared. Updates are reviewed, not automatically merged.
- Private vulnerability reporting enabled; see [SECURITY.md](../SECURITY.md).
- Actions disabled: there are no workflows and no remote CI pass is claimed.
  If CI is added later, review permissions before enabling Actions. The retained
  default token permission is read-only and workflow PR approval is disabled.
- Main protection applies to administrators, rejects force pushes and deletion,
  and requires linear history. Direct normal pushes remain allowed for solo
  maintenance; mandatory PR approvals and nonexistent CI checks are not required.
- No collaborators were added; the sole collaborator remains the owner.

GitHub scanning is asynchronous. Enabled protection and any zero-alert snapshot
are not a completed security audit or a guarantee of vulnerability absence.
Normal VM reboots remain distinct from sudden power loss and boot-zero-gap;
neither unmeasured capability is claimed passed.
