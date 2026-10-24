# MIT license adoption

Keepweft adopts [MIT](../LICENSE), copyright 2026 Andrew Yuan. Repository
visibility remains Private. README, current workflow documents and package
metadata agree; historical reviews explicitly retain their pre-MIT context.
[Third-party scope](THIRD_PARTY.md) records upstream terms and distribution scope.

## Actual checks

- Native macOS: all 83 formal tests passed, with zero failures/errors/skips and
  the same test IDs as the last full qualification.
- Built a new wheel and source distribution. Both declare `License-Expression:
  MIT` and include the exact project LICENSE. The wheel declares no extra Python
  runtime dependencies and contains only project modules and distribution metadata.
- Installed the new wheel into a fresh local virtual environment without fetching
  dependencies; isolated import, installed MIT metadata and license checks passed.
- Wheel product hashes equal the current runtime modules. Runtime imports are
  project modules and standard library only. Build/venv artifacts remain ignored.
- Compared the current qualification manifest with run `21c52afcecce99d5`:
  only `pyproject.toml` changed (MIT license metadata). Runtime, tests and tools
  are byte-identical. The historical JSON/HTML receipts remain unchanged and their
  existing verifier still passes.

The current source fingerprint is
`ec440168f9e53de1826ca00dad76cf11ed7698f8781d450551257d4c6cdece26`.
It differs from the historical Linux qualification fingerprint
`2e021cf36ce897de501d1325879dccefdf42e07f3ec394a5f5390740acea4478`.
[Machine-readable packaging/source/native-test checks](../evidence/licensing/verification.json)
retain both fingerprints and package contents/hashes. This is a packaging and
license check, not a new Linux VM, performance or recovery qualification. No
historical measurement is relabelled as a run of the new package.
