"""Executable dependency-direction rules for the API layers."""

import ast
from collections.abc import Iterable
from importlib.util import resolve_name
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).parents[1] / "app"
EXTERNAL_ADAPTERS = (
    "celery",
    "fastapi",
    "httpx2",
    "kombu",
    "minio",
    "nvidia",
    "openai",
    "pydantic",
    "psycopg",
    "qdrant_client",
    "redis",
    "sqlalchemy",
)


def imported_modules(source_file: Path) -> Iterable[str]:
    """Yield absolute module names present in Python import statements."""

    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    source_parts = source_file.relative_to(APP_ROOT).with_suffix("").parts
    package = ".".join(("app", *source_parts[:-1]))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module is not None:
                yield node.module
            elif node.level > 0:
                relative_name = f"{'.' * node.level}{node.module or ''}"
                resolved_module = resolve_name(relative_name, package)
                if node.module is None:
                    yield from (f"{resolved_module}.{alias.name}" for alias in node.names)
                else:
                    yield resolved_module


def is_forbidden(module: str, forbidden: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in forbidden)


@pytest.mark.parametrize(
    ("layer", "forbidden"),
    [
        pytest.param(
            "domain",
            (
                *EXTERNAL_ADAPTERS,
                "app.api",
                "app.application",
                "app.core",
                "app.infrastructure",
                "app.observability",
                "app.rag",
                "app.security",
                "ntc_contracts",
                "ntc_shared",
            ),
            id="domain-is-framework-independent",
        ),
        pytest.param(
            "application",
            (
                *EXTERNAL_ADAPTERS,
                "app.api",
                "app.core",
                "app.infrastructure",
                "app.observability",
                "app.rag",
                "app.security",
                "ntc_contracts",
            ),
            id="application-points-inward",
        ),
        pytest.param(
            "api",
            (
                "app.core",
                "app.domain",
                "app.infrastructure",
                "app.observability",
                "app.rag",
                # app.security is intentionally allowed: it is the HTTP transport
                # auth adapter and lives at the same layer boundary as api.
            ),
            id="http-transport-uses-application-boundary",
        ),
    ],
)
def test_layer_dependency_direction(layer: str, forbidden: tuple[str, ...]) -> None:
    violations: list[str] = []
    for source_file in (APP_ROOT / layer).rglob("*.py"):
        for imported_module in imported_modules(source_file):
            if is_forbidden(imported_module, forbidden):
                violations.append(f"{source_file.relative_to(APP_ROOT)} imports {imported_module}")

    assert not violations, "Layer dependency violations:\n" + "\n".join(sorted(violations))
