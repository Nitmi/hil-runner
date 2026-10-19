# Fetch only the pinned public debugger release and a source-bound Replay fixture.
param([Parameter(Mandatory)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$directory = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $directory) { throw 'Use a new output directory' }
New-Item -ItemType Directory -Path $directory -ErrorAction Stop | Out-Null
$archiveName = 'embedded-debugger-0.2.5-x86_64-pc-windows-msvc.zip'
$archive = Join-Path $directory $archiveName
$revision = 'dcff1e304b6e38ae0993649539ca6e03bddfab7a'
gh release download v0.2.5 --repo Nitmi/embedded-debugger --pattern $archiveName --dir $directory
if ($LASTEXITCODE -ne 0) { throw 'Debugger release download failed' }
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -cne '835bb47a5b1c536395a7ca1382873fea460f5c035069b6be9b3c928ee06fa17c') {
    throw 'Debugger archive checksum mismatch'
}
$verification = & gh attestation verify $archive --repo Nitmi/embedded-debugger `
    --source-ref refs/tags/v0.2.5 --source-digest $revision --signer-digest $revision `
    --cert-identity 'https://github.com/Nitmi/embedded-debugger/.github/workflows/binary-release.yml@refs/tags/v0.2.5' `
    --deny-self-hosted-runners --predicate-type https://slsa.dev/provenance/v1 --format json
if ($LASTEXITCODE -ne 0) { throw 'Debugger provenance verification failed' }
$verification | Set-Content -LiteralPath (Join-Path $directory 'debugger-attestation-verification.json') -Encoding utf8
Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $directory 'installed')
$executable = Join-Path $directory 'installed/embedded-debugger-0.2.5-x86_64-pc-windows-msvc/embedded-debugger.exe'
$executableHash = 'e83f4483f07d63630cb90dd964b6eab1b619d4de8b1ba1c7e69f9a677119cb2d'
if ((Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant() -cne $executableHash) {
    throw 'Debugger executable checksum mismatch'
}
$fixture = Join-Path $directory 'stm32g4.json'
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/Nitmi/embedded-debugger/$revision/examples/replay/stm32g4.json" -OutFile $fixture -TimeoutSec 60
if ((Get-FileHash -LiteralPath $fixture -Algorithm SHA256).Hash.ToLowerInvariant() -cne '3954dd1ddba111494a4b0310c43f2311777c6691fdeecb1a677364df3b73657f') {
    throw 'Replay fixture checksum mismatch'
}
$values = [ordered]@{
    HIL_NATIVE_DEBUGGER_TEST_EXE = $executable
    HIL_NATIVE_DEBUGGER_TEST_SHA256 = $executableHash
    HIL_NATIVE_DEBUGGER_TEST_VERSION = '0.2.5'
    HIL_NATIVE_REPLAY_FIXTURE = $fixture
}
if ($env:GITHUB_ENV) {
    foreach ($entry in $values.GetEnumerator()) {
        "$($entry.Key)=$($entry.Value)" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
    }
}
$values | ConvertTo-Json
