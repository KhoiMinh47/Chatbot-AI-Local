"""Phase 0 import and CUDA smoke for the isolated Python 3.14 lock."""

from __future__ import annotations

import ctypes
import importlib
import json
import platform
import sys
from importlib.metadata import distribution as get_distribution


PACKAGES = {
    "alembic": "alembic",
    "celery": "celery",
    "docling": "docling",
    "fastapi": "fastapi",
    "langchain-openai": "langchain_openai",
    "langgraph": "langgraph",
    "minio": "minio",
    "psycopg": "psycopg",
    "pydantic-settings": "pydantic_settings",
    "qdrant-client": "qdrant_client",
    "redis": "redis",
    "sqlalchemy": "sqlalchemy",
    "uvicorn": "uvicorn",
}


def package_version(distribution: str) -> str:
    from importlib.metadata import version

    return version(distribution)


def main() -> None:
    imports: dict[str, str] = {}
    for distribution, module_name in PACKAGES.items():
        importlib.import_module(module_name)
        imports[distribution] = package_version(distribution)

    # Exercise the concrete APIs used by the compatibility decision, including
    # UTF-8 validation, graph construction, and Docling's primary converter.
    from docling.document_converter import DocumentConverter
    from fastapi import FastAPI
    from langgraph.graph import END, START, StateGraph
    from pydantic import BaseModel

    class VietnameseText(BaseModel):
        text: str

    assert VietnameseText(text="Xin chào Việt Nam").text == "Xin chào Việt Nam"
    assert isinstance(FastAPI(), FastAPI)
    assert DocumentConverter is not None
    graph = StateGraph(dict)
    graph.add_edge(START, END)
    graph.compile()

    import torch

    cusparselt_library = get_distribution("nvidia-cusparselt-cu13").locate_file(
        "nvidia/cusparselt/lib/libcusparseLt.so.0"
    )
    ctypes.CDLL(str(cusparselt_library))

    assert torch.cuda.is_available(), "CUDA is unavailable to PyTorch"
    device = torch.device("cuda")
    result = torch.tensor([[1.0, 2.0]], device=device) @ torch.tensor(
        [[3.0], [4.0]], device=device
    )
    torch.cuda.synchronize()
    assert result.item() == 11.0

    evidence = {
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "imports": imports,
        "cusparselt": {
            "library": str(cusparselt_library),
            "ctypes_load": "pass",
        },
        "torch_cuda": {
            "torch_version": torch.__version__,
            "available": torch.cuda.is_available(),
            "device_count": torch.cuda.device_count(),
            "device_name": torch.cuda.get_device_name(0),
            "capability": list(torch.cuda.get_device_capability(0)),
            "matrix_multiply": result.item(),
        },
        "status": "pass",
    }
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
