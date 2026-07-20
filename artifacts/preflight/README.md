# Phase 0 preflight evidence

Run the read-only host inventory from the repository root:

```bash
./scripts/preflight.sh
```

Each execution creates a UTC-timestamp-and-process-ID directory and refuses to
reuse an existing destination, so concurrent runs cannot truncate or interleave
one evidence bundle. The current reviewed run is
[`20260713T090800Z`](20260713T090800Z/).

The script captures only the commands required by the master plan plus selected
local image metadata. `docker info` is projected to an explicit non-secret field
allowlist. The capture deliberately excludes container environments, Docker
registry configuration, proxy values, and credential values.
`credential-presence.txt` records presence/absence only; `secret-scan.txt`
records the high-confidence secret-pattern scan result without echoing matches.
The script collects all checks, then exits nonzero if any row in
`command-status.tsv` has a nonzero exit code.

The reviewed run also contains independently captured Phase 0 evidence:

- exact registry manifest for the one local NIM image;
- normalized exact-tag candidate manifest checks plus capture provenance (using
  `docker manifest inspect` and `--verbose`, without pulling layers);
- GB10-compatible profile listing from that image;
- Python 3.14 dependency lock/install logs and compatibility summary.
- an offline locked-sync recheck after the initial normal locked install.

Artifacts are evidence for this host at one point in time, not portable
deployment configuration.
