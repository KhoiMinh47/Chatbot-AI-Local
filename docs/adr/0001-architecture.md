# ADR 0001 — Single-host modular architecture, Nginx, and Qdrant baseline

- Status: Accepted
- Date: 2026-07-13
- Phase: 0
- Decision gate: Architecture compatibility
- Owners: NTC Local RAG team

## Context

The product targets one DGX Spark-class host and a small development team. The
application needs clear domain boundaries without paying the operational cost
of a distributed microservice backend. Two choices left open by the master plan
must also be closed before infrastructure work: Nginx versus Traefik for the
gateway, and the vector database baseline.

## Evidence and constraints

- The target is a single `aarch64` host with one NVIDIA GB10, 20 CPU cores, and
  121.7 GiB RAM. See
  [`artifacts/preflight/20260713T090800Z/preflight.txt`](../../artifacts/preflight/20260713T090800Z/preflight.txt).
- Local ARM64 images exist for Nginx and Qdrant, but their currently available
  tags are not a Phase 2 pinning decision. Every deployment reference still
  needs an exact tag and registry digest before use.
- SSE streams, large uploads, rate limits, TLS termination, and tunnel traffic
  must enter through one gateway. No datastore or NIM may publish a host port
  in the public profile.
- Document ACL filtering must happen inside vector retrieval. GPU vector search
  has no demonstrated bottleneck in the MVP workload.

## Options considered

### Backend topology

1. Modular monolith for product/domain code, with worker, NIM, data, and
   observability services in separate containers.
2. Full product microservices.

The second option adds network contracts, distributed transactions, and more
deployment failure modes before the workload requires independent scaling.

### Gateway

1. Nginx with explicit, reviewed routes.
2. Traefik with Docker service discovery and dynamic labels.

Traefik is useful when dynamic service discovery is a primary requirement.
This deployment has a small, static route set. Nginx keeps SSE buffering,
upload limits, timeouts, rate limits, and public exposure explicit and avoids
granting the gateway access to the Docker socket.

### Vector database

1. Qdrant for the MVP.
2. Milvus with GPU/CAGRA/cuVS from the start.

Qdrant has the needed payload filtering and operational shape for one host.
The GPU option is only justified after a retrieval benchmark proves vector
search is a bottleneck.

## Decision

- Use a modular monolith for the FastAPI product backend.
- Keep ingestion workers, NVIDIA NIMs, PostgreSQL, Redis, RabbitMQ, MinIO,
  Qdrant, and observability components as separate service boundaries.
- Use **Nginx** as the only reverse proxy/API gateway.
- Use **Qdrant** as the MVP vector database baseline.
- Only Nginx may publish application entry ports. All other service traffic is
  internal. A future tunnel must target Nginx only.
- Defer image pinning and all runtime configuration to Phase 2. This ADR does
  not create or start Compose services.

## Consequences

### Positive

- Business transactions and authorization remain easy to reason about.
- Routes and public exposure are auditable in one place.
- Qdrant can enforce tenant/document/ACL payload filters during search.
- The service boundaries can still be split or scaled later if measurements
  justify it.

### Negative and risks

- Nginx requires explicit configuration for SSE proxy buffering and timeouts.
- A modular monolith requires enforced module boundaries to avoid becoming a
  tightly coupled codebase.
- Qdrant is CPU-based in the baseline; a much larger corpus may require a new
  benchmark and ADR.

## Validation

- Host and local image architecture inventory completed in Phase 0.
- Phase 2 must validate exact ARM64 registry manifests, immutable digests,
  health checks, public port exposure, SSE behavior, and restart persistence.
- ACL correctness remains a Phase 5/7 integration gate.

## Unknowns and blockers

- Exact Nginx and Qdrant release tags/digests are intentionally not chosen in
  Phase 0.
- No throughput claim has been made for Qdrant on the final corpus.

## Revisit when

- Reproducible profiling shows Qdrant dominates end-to-end retrieval latency.
- The application must span multiple hosts or independently deploy product
  modules.
- A supported dynamic routing requirement materially outweighs the cost of
  gateway service discovery.

## References

- [Master plan: architecture](../../NTC_NVIDIA_LOCAL_RAG_CHATBOT_MASTER_PLAN.md#4-kiến-trúc-mục-tiêu)
- [Master plan: Qdrant baseline](../../NTC_NVIDIA_LOCAL_RAG_CHATBOT_MASTER_PLAN.md#52-vì-sao-qdrant-là-baseline)
- [Master plan: Docker Compose design](../../NTC_NVIDIA_LOCAL_RAG_CHATBOT_MASTER_PLAN.md#16-docker-compose-design)

