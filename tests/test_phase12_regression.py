from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

# Adjust path so python matches the monorepo package structures
sys.path.insert(0, str(REPOSITORY_ROOT / "apps/api"))

from app.application.rag import FINAL_USER_TEMPLATE, PROMPT_SHA256, SYSTEM_PROMPT  # noqa: E402
from app.core.settings import (  # noqa: E402
    SELECTED_NIM_LLM_MODEL,
    SELECTED_NIM_LLM_MODEL_VERSION,
    ApiSettings,
)

from scripts.phase6_winner_e2e import (  # noqa: E402
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    EMBEDDING_MODEL_VERSION,
)


def test_configuration_freeze():
    """Verify that RAG Prompts, Model choices, and indexing dimensions are strictly frozen."""
    # 1. Verify Prompt contract
    assert PROMPT_SHA256 == "de7e06df0c49e06170b9a39be06c7a3eb95c4cb04b5c331a6726bbeb2713ec84"
    assert "You are the grounded assistant for NTC's local knowledge system." in SYSTEM_PROMPT
    assert "AUTHORIZED CONTEXT" in FINAL_USER_TEMPLATE

    # 2. Verify LLM configuration
    assert SELECTED_NIM_LLM_MODEL == "nvidia/nemotron-nano-9b-v2"
    assert SELECTED_NIM_LLM_MODEL_VERSION == "1.0.0"

    # 3. Verify Embedding configuration
    assert EMBEDDING_MODEL == "nvidia/llama-nemotron-embed-300m-v2"
    assert EMBEDDING_MODEL_VERSION == "1.13.0"
    assert EMBEDDING_DIMENSION == 2048

    # 4. Verify API Default settings are not altered
    settings = ApiSettings()
    assert settings.nim_llm_model is None or settings.nim_llm_model == SELECTED_NIM_LLM_MODEL
