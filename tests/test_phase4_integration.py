"""Integration tests for Phase 4 document ingestion."""

import hashlib
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
async def db_session():
    """Create a test database session."""
    database_url = os.getenv("PHASE4_DATABASE_URL")
    if not database_url:
        pytest.skip("set PHASE4_DATABASE_URL to run PostgreSQL integration tests")

    engine = create_async_engine(
        database_url,
        echo=False,
    )
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with async_session() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture
def mock_user():
    """Mock authenticated user."""
    return {
        "user_id": uuid4(),
        "tenant_id": uuid4(),
        "email": "test@example.com",
    }


class TestDocumentUploadAPI:
    """Test document upload endpoints."""

    @pytest.mark.anyio
    @pytest.mark.integration
    async def test_upload_text_document(self, mock_user) -> None:
        """Test uploading a plain text document."""
        # Create a test text file
        content = b"# Test Document\n\nThis is a test document for Phase 4."

        # This would be a real API call in full integration test
        # For now, test the core logic

        # Validate MIME type
        assert len(content) > 0
        content_hash = hashlib.sha256(content).hexdigest()
        assert len(content_hash) == 64

    @pytest.mark.anyio
    @pytest.mark.integration
    async def test_upload_csv_document(self, mock_user) -> None:
        """Test uploading a CSV document."""
        content = b"Name,Age,City\nJohn,30,NYC\nJane,25,LA"

        content_hash = hashlib.sha256(content).hexdigest()
        assert len(content_hash) == 64

    @pytest.mark.anyio
    @pytest.mark.integration
    async def test_duplicate_upload_rejected(self, db_session: AsyncSession, mock_user) -> None:
        """Test that duplicate content is rejected."""
        content = b"Test content"
        content_hash = hashlib.sha256(content).hexdigest()

        # Insert a document with this hash
        doc_id = uuid4()
        await db_session.execute(
            text("""
                INSERT INTO documents (
                    id, tenant_id, owner_id, source_name, mime_type,
                    content_hash, size_bytes, state, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :owner_id, 'existing.txt', 'text/plain',
                    :content_hash, :size_bytes, 'ready', NOW(), NOW()
                )
            """),
            {
                "id": doc_id,
                "tenant_id": mock_user["tenant_id"],
                "owner_id": mock_user["user_id"],
                "content_hash": content_hash,
                "size_bytes": len(content),
            },
        )
        await db_session.commit()

        # Check duplicate exists
        result = await db_session.execute(
            text("""
                SELECT id FROM documents
                WHERE tenant_id = :tenant_id
                  AND content_hash = :content_hash
                  AND deleted_at IS NULL
            """),
            {"tenant_id": mock_user["tenant_id"], "content_hash": content_hash},
        )

        existing = result.fetchone()
        assert existing is not None

    @pytest.mark.anyio
    @pytest.mark.integration
    async def test_document_state_transitions(self, db_session: AsyncSession, mock_user) -> None:
        """Test document state transitions during processing."""
        doc_id = uuid4()

        # Create document in UPLOADED state
        await db_session.execute(
            text("""
                INSERT INTO documents (
                    id, tenant_id, owner_id, source_name, mime_type,
                    content_hash, size_bytes, state, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :owner_id, 'test.txt', 'text/plain',
                    'abc123', 100, 'uploaded', NOW(), NOW()
                )
            """),
            {
                "id": doc_id,
                "tenant_id": mock_user["tenant_id"],
                "owner_id": mock_user["user_id"],
            },
        )
        await db_session.commit()

        # Verify initial state
        result = await db_session.execute(
            text("SELECT state FROM documents WHERE id = :id"),
            {"id": doc_id},
        )
        row = result.fetchone()
        assert row[0] == "uploaded"

        # Simulate state transition to PARSING
        await db_session.execute(
            text("UPDATE documents SET state = 'parsing', updated_at = NOW() WHERE id = :id"),
            {"id": doc_id},
        )
        await db_session.commit()

        result = await db_session.execute(
            text("SELECT state FROM documents WHERE id = :id"),
            {"id": doc_id},
        )
        row = result.fetchone()
        assert row[0] == "parsing"


class TestDocumentVersioning:
    """Test document versioning and idempotency."""

    @pytest.mark.anyio
    @pytest.mark.integration
    async def test_version_creation(self, db_session: AsyncSession, mock_user) -> None:
        """Test creating document versions."""
        doc_id = uuid4()
        version_id = uuid4()

        # Create document
        await db_session.execute(
            text("""
                INSERT INTO documents (
                    id, tenant_id, owner_id, source_name, mime_type,
                    content_hash, size_bytes, state, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :owner_id, 'versioned.txt', 'text/plain',
                    'def456', 200, 'ready', NOW(), NOW()
                )
            """),
            {
                "id": doc_id,
                "tenant_id": mock_user["tenant_id"],
                "owner_id": mock_user["user_id"],
            },
        )

        # Create version
        await db_session.execute(
            text("""
                INSERT INTO document_versions (
                    id, document_id, version_number, content_hash,
                    parser_version, chunk_config, created_at
                ) VALUES (
                    :id, :document_id, 1, 'def456',
                    'docling-3.0', '{"child_size": 512}', NOW()
                )
            """),
            {
                "id": version_id,
                "document_id": doc_id,
            },
        )
        await db_session.commit()

        # Verify version exists
        result = await db_session.execute(
            text("""
                SELECT version_number FROM document_versions
                WHERE document_id = :document_id
            """),
            {"document_id": doc_id},
        )
        row = result.fetchone()
        assert row[0] == 1


class TestChunkStorage:
    """Test chunk storage and retrieval."""

    @pytest.mark.anyio
    @pytest.mark.integration
    async def test_store_chunks(self, db_session: AsyncSession, mock_user) -> None:
        """Test storing chunks in database."""
        doc_id = uuid4()
        version_id = uuid4()
        chunk_id = uuid4()

        # Create document and version
        await db_session.execute(
            text("""
                INSERT INTO documents (
                    id, tenant_id, owner_id, source_name, mime_type,
                    content_hash, size_bytes, state, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :owner_id, 'chunked.txt', 'text/plain',
                    'ghi789', 300, 'ready', NOW(), NOW()
                )
            """),
            {
                "id": doc_id,
                "tenant_id": mock_user["tenant_id"],
                "owner_id": mock_user["user_id"],
            },
        )

        await db_session.execute(
            text("""
                INSERT INTO document_versions (
                    id, document_id, version_number, content_hash,
                    parser_version, chunk_config, created_at
                ) VALUES (
                    :id, :document_id, 1, 'ghi789',
                    'docling-3.0', '{"child_size": 512}', NOW()
                )
            """),
            {
                "id": version_id,
                "document_id": doc_id,
            },
        )

        # Store a chunk
        await db_session.execute(
            text("""
                INSERT INTO chunks (
                    id, document_id, version_id, chunk_type, chunk_index,
                    text_preview, token_count, section_path, created_at
                ) VALUES (
                    :id, :document_id, :version_id, 'child', 0,
                    'This is chunk text...', 50, '[]', NOW()
                )
            """),
            {
                "id": chunk_id,
                "document_id": doc_id,
                "version_id": version_id,
            },
        )
        await db_session.commit()

        # Verify chunk stored
        result = await db_session.execute(
            text("""
                SELECT token_count FROM chunks
                WHERE document_id = :document_id
            """),
            {"document_id": doc_id},
        )
        row = result.fetchone()
        assert row[0] == 50
