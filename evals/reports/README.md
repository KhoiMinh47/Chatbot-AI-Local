# Evaluation reports

Generated reports belong here and must identify whether they are measured live data,
offline executable-contract evidence, or human annotation. Mock/simulated metrics
must never be used for an acceptance gate.

The legacy `artifacts/phase-12/evaluation-report.json` is explicitly marked invalid
because its former runner fabricated observations and latency. The replacement
runner fails closed when measured observations are absent.
