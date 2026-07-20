"""PostgreSQL full-text lexical retrieval with mandatory tenant/ACL filters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domain.retrieval import AccessScope, ChunkPayload, SearchHit


def _principal_ids(principals: tuple[str, ...]) -> tuple[tuple[UUID, ...], tuple[UUID, ...]]:
    users: list[UUID] = []
    groups: list[UUID] = []
    for principal in principals:
        kind, separator, raw_id = principal.partition(":")
        if not separator or kind not in {"user", "group"}:
            continue
        try:
            principal_id = UUID(raw_id)
        except ValueError:
            continue
        (users if kind == "user" else groups).append(principal_id)
    return tuple(users), tuple(groups)


class PostgresLexicalIndex:
    """Rank child chunks with PostgreSQL FTS without widening document access."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def search(
        self,
        *,
        query: str,
        scope: AccessScope,
        index_version: str,
        limit: int,
    ) -> tuple[SearchHit, ...]:
        if not query.strip():
            raise ValueError("lexical query must not be blank")
        if not 1 <= limit <= 100:
            raise ValueError("lexical limit must be between 1 and 100")
        user_ids, group_ids = _principal_ids(scope.acl_principals)
        if not user_ids and not group_ids:
            return ()

        statement = text("""
            WITH search_query AS (
                SELECT websearch_to_tsquery('simple', :query) AS value
            )
            SELECT
                c.id,
                c.document_id,
                c.version_id,
                c.parent_chunk_id,
                c.text,
                c.token_count,
                c.content_hash,
                c.index_version,
                c.page,
                c.slide,
                c.sheet,
                c.cell_range,
                c.line_start,
                c.line_end,
                c.section_path,
                c.language,
                c.created_at,
                d.tenant_id,
                d.owner_id,
                d.source_name,
                d.mime_type,
                ARRAY(
                    SELECT da.principal_type || ':' || da.principal_id::text
                    FROM app.document_acls AS da
                    WHERE da.document_id = d.id
                    ORDER BY da.principal_type, da.principal_id
                ) AS document_acl_principals,
                ts_rank_cd(
                    to_tsvector('simple', c.text),
                    search_query.value,
                    32
                ) AS lexical_score
            FROM app.chunks AS c
            JOIN app.documents AS d ON d.id = c.document_id
            CROSS JOIN search_query
            WHERE d.tenant_id = :tenant_id
              AND d.deleted_at IS NULL
              AND d.state = 'ready'
              AND d.current_version_id = c.version_id
              AND c.chunk_type = 'child'
              AND c.index_version = :index_version
              AND (
                    d.owner_id = ANY(CAST(:user_ids AS uuid[]))
                    OR EXISTS (
                        SELECT 1
                        FROM app.document_acls AS allowed
                        WHERE allowed.document_id = d.id
                          AND (
                            (allowed.principal_type = 'user'
                             AND allowed.principal_id = ANY(CAST(:user_ids AS uuid[])))
                            OR
                            (allowed.principal_type = 'group'
                             AND allowed.principal_id = ANY(CAST(:group_ids AS uuid[])))
                          )
                    )
              )
              AND (
                    NOT :has_document_filter
                    OR c.document_id = ANY(CAST(:document_ids AS uuid[]))
              )
              AND to_tsvector('simple', c.text) @@ search_query.value
            ORDER BY lexical_score DESC, c.id
            LIMIT :limit
        """)
        params = {
            "query": query,
            "tenant_id": scope.tenant_id,
            "index_version": index_version,
            "user_ids": list(user_ids),
            "group_ids": list(group_ids),
            "has_document_filter": bool(scope.document_ids),
            "document_ids": list(scope.document_ids),
            "limit": limit,
        }
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement, params)).mappings().all()

        hits: list[SearchHit] = []
        for row in rows:
            record = cast(Mapping[str, object], row)
            owner_id = cast(UUID, record["owner_id"])
            raw_acl = cast(list[str] | None, record["document_acl_principals"])
            acl = tuple(dict.fromkeys((f"user:{owner_id}", *(raw_acl or []))))
            raw_section = cast(list[object] | None, record["section_path"])
            payload = ChunkPayload(
                tenant_id=cast(UUID, record["tenant_id"]),
                document_id=cast(UUID, record["document_id"]),
                version_id=cast(UUID, record["version_id"]),
                chunk_id=cast(UUID, record["id"]),
                parent_id=cast(UUID | None, record["parent_chunk_id"]),
                owner_id=owner_id,
                acl_principals=acl,
                source_name=cast(str, record["source_name"]),
                mime_type=cast(str, record["mime_type"]),
                page=cast(int | None, record["page"]),
                slide=cast(int | None, record["slide"]),
                sheet=cast(str | None, record["sheet"]),
                cell_range=cast(str | None, record["cell_range"]),
                line_start=cast(int | None, record["line_start"]),
                line_end=cast(int | None, record["line_end"]),
                section_path=tuple(str(value) for value in (raw_section or [])),
                language=cast(str | None, record["language"]) or "unknown",
                text=cast(str, record["text"]),
                token_count=cast(int, record["token_count"]),
                content_hash=cast(str, record["content_hash"]),
                index_version=cast(str, record["index_version"]),
                created_at=record["created_at"],  # type: ignore[arg-type]
            )
            hits.append(
                SearchHit(
                    point_id=payload.chunk_id,
                    score=float(cast(float | int, record["lexical_score"])),
                    payload=payload,
                )
            )
        return tuple(hits)
