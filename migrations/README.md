# Database migrations

Revision `0001` establishes the empty `app` PostgreSQL schema boundary and
Alembic history. Later reviewed Phase 4 and Phase 6 revisions add document,
ingestion and redacted generation-trace tables. Those tables currently live in
the default `public` schema; moving them into `app` requires a separate data
migration and matching query changes. No auth, user, conversation or public
chat tables have been added because those belong to Phase 7.

Run migrations through `make migrate` after the Phase 2 PostgreSQL service is
healthy. The command reads the database password from the local Compose secret
file and never prints it.
