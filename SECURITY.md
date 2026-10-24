# Security policy

Keepweft is a bounded local MVP, not a production backup or disaster-recovery
guarantee. See the [README](README.md) for the delivered scope and unqualified
capabilities. The current main branch is maintained; no supported release matrix
or security response SLA is promised.

Report suspected vulnerabilities through GitHub's
[private vulnerability reporting](https://github.com/andrew29mo/keepweft/security/advisories/new).
Do not include real source databases, credentials, private paths or customer data.
Use generated demonstration data for reproductions. Avoid publishing an exploit
or sensitive details in a public issue before coordinated review.

The service trusts same-UID processes and uses owner-only local sockets/stores.
Do not expose it as a network or multi-tenant service. Same-device backup copies
do not protect against device loss. Abrupt power loss, boot zero-gap, encryption,
remote storage and production service cutover remain unqualified.
