# Synthetic native saved waveform examples

AD3 `passed`, `failed`, `invalid` and `mixed` and four-channel SDS804X `sds`
contain synthetic captures and actual lab-instruments 0.9.0 check/JUnit output.
No physical instrument, SDK, analog accuracy or historical execution authenticity
is established. Each import manifest binds exact bytes; recorded absolute paths
are labels and must not be opened. SDS includes all native files, even empty RX.

Use each `import.json` with its computed SHA-256 and a new output path. Native
verification can be repeated with explicitly selected local spec/capture/report
paths; preserve the new stdout/XML and select their new hashes in a new import
manifest. Do not rewrite old reports or treat formatting changes as identical
original bytes. Trace fixtures are self-contained copies of resulting bundles.
