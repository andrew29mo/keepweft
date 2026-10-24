# Third-party scope

Keepweft has no selected project license yet. No MIT/Apache or other open-source
license grant is implied by this Private repository.

Runtime code uses Python's standard library and SQLite. Python retains the PSF
license; SQLite is in the public domain according to https://sqlite.org/copyright.html.
Build tooling (setuptools/wheel), Ubuntu system packages and Colima/Lima remain
external dependencies with their respective terms. No upstream runtime source,
compiler output, VM image, package wheel or third-party binary is committed.

The isolated Linux validation builds SQLite 3.54.1 from the official HTTPS
amalgamation archive and verifies the sqlite3.c SHA3-256 published in release
history: https://sqlite.org/changes.html. The receipt records archive hash,
compiler flags, actual library hash, loaded-library mapping and runtime source ID.
The native SQLite version is reported separately. Passing experiments does not
certify arbitrary distro backports or SQLite builds.
