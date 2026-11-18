# Historical engineering handoffs

This directory preserves the pre-release engineering record: batch briefs,
independent Architect reviews, correction rounds, final acceptance and the raw
evidence produced with them. It exists for auditability, not as operating
instructions.

- **Do not treat these documents as current guidance.** Current installation,
  configuration, usage and recovery instructions live in
  [`docs/installation.md`](../installation.md),
  [`docs/configuration.md`](../configuration.md) and
  [`docs/troubleshooting.md`](../troubleshooting.md).
- **Paths are historical.** Commands in these files cite the maintainer's build
  machine (for example `/home/abdullah/...`), a fixed OpenCode binary location and
  disposable `/tmp` probes. They are not defaults, requirements or portable
  instructions.
- **Dates and counts are as executed.** Findings are not rewritten after the
  fact; later corrections appear as new documents with their own dates.
- **Evidence may be large.** Logs under `evidence/` are raw test output. They
  contain no credentials, session transcripts or private project source. Report
  files and fixtures are sanitized.

The authoritative behavior contract is the code plus the test suite; see
[`docs/validation.md`](../validation.md) for the current evidence summary.
