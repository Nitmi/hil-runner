# Verify and install a release

HIL Runner is delivered as a Python wheel and source archive through GitHub
Releases. It requires Python 3.11+ and has no runtime dependencies. Managed native
execution is Windows-only; Ubuntu supports the cooperative lease interface.
There is no standalone executable or PyPI publication in this release.

## Release identity and verification

Download the wheel, source archive, `release-manifest.json` and `SHA256SUMS` from
the same release into a new directory. Keep attestation bundles and command logs
in a separate directory. Check the published tag's commit against the release
notes or another trusted record before verifying provenance.

For each of the four assets, use GitHub CLI to enforce the repository, tag,
source commit, signer commit and workflow identity. Replace `<asset>` and
`<source-commit>` with the chosen asset path and the full expected commit:

```powershell
gh attestation verify '<asset>' --repo Nitmi/hil-runner `
  --source-ref refs/tags/v0.7.0 `
  --source-digest '<source-commit>' --signer-digest '<source-commit>' `
  --cert-identity 'https://github.com/Nitmi/hil-runner/.github/workflows/python-release.yml@refs/tags/v0.7.0' `
  --deny-self-hosted-runners --predicate-type https://slsa.dev/provenance/v1
```

All four must pass. The release helper checks hashes, sizes, package metadata,
archive paths and agreement between wheel/source runtime files:

```powershell
python scripts/release.py verify '<download-directory>' --source-revision '<source-commit>'
```

Run that helper from a trusted matching source checkout, not from an unverified
download. Integrity checks alone do not authenticate a publisher. The helper
never extracts archives, starts HIL or accesses hardware. Source builds also
compare every archived source file (except generated `PKG-INFO`) to its Git blob.

## Isolated installation

After verification, create a new environment and install the exact wheel without
dependency or package-index resolution:

```powershell
uv venv --python 3.11 'D:\Code\tools\hil-runner\0.7.0\venv'
uv pip install --python 'D:\Code\tools\hil-runner\0.7.0\venv\Scripts\python.exe' `
  --no-index --no-deps '<download-directory>\embedded_hil_runner-0.7.0-py3-none-any.whl'
& 'D:\Code\tools\hil-runner\0.7.0\venv\Scripts\hil-runner.exe' --version
& 'D:\Code\tools\hil-runner\0.7.0\venv\Scripts\hil-runner.exe' managed --help
```

Use an unused installation directory. Ubuntu uses `venv/bin/python` and
`venv/bin/hil-runner`. The source checkout's `scripts/smoke_installed.py`, run by
the new environment's Python, checks that imports come from that environment,
packaged schemas exist and a synthetic lease plan has no hardware effects.

The environment can be used by its absolute paths; no persistent PATH change or
system Python installation is needed. Keep previous versions until their live
owners and all managed child processes have stopped.

## Native components and station selection

The wheel does not include baud or embedded-debugger. Windows managed execution
is qualified against official debugger 0.2.5; its exact hashes are recorded in
[managed workflow](managed.md). Each managed plan must bind its own executable,
firmware and contract paths/hashes. Installing this wheel does not change a
Toolkit workstation lock or approve a board operation.

The release workflow runs ordinary tests against the installed wheel and Windows
native integrations against the verified official debugger, Replay and a Rust
fake baud program. The latter has no hardware API. This proves host integration;
physical qualification remains limited to the documented DK run.

## Reproduce release assets

From a clean committed checkout with the matching tag:

```powershell
uv sync --locked --extra dev
uv run --locked python scripts/release.py build --tag v0.7.0 --output-dir '<new-directory>'
```

The pinned build backend and locked tools produce wheel/source assets plus a
source-bound manifest and checksums. CI builds them twice and requires byte-for-
byte equality before attestation. Local builds do not create a GitHub attestation.
