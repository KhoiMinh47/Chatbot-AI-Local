from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_SCRIPT = REPOSITORY_ROOT / "scripts" / "preflight.sh"
NIM_SMOKE_SCRIPT = REPOSITORY_ROOT / "scripts" / "nim-smoke.sh"
PHASE1_SMOKE_SCRIPT = REPOSITORY_ROOT / "scripts" / "smoke-phase1.sh"
SOURCE_SECRET_SCAN_SCRIPT = REPOSITORY_ROOT / "scripts" / "source-secret-scan.sh"
PHASE1_SMOKE_TOOLS = ("uv", "pnpm", "curl", "jq", "ps", "setsid", "ss", "tr")
PHASE1_SMOKE_READY = (
    all(shutil.which(tool) for tool in PHASE1_SMOKE_TOOLS)
    and (REPOSITORY_ROOT / "node_modules").is_dir()
)


class MockNimState:
    def __init__(self) -> None:
        self.status = 200
        self.llm_content = "OK"
        self.embedding = [0.1, 0.2]
        self.ranking_indices = [0, 1]
        self.llm_system_prompts: list[str] = []


def handler_for(state: MockNimState) -> type[BaseHTTPRequestHandler]:
    class MockNimHandler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *args: Any) -> None:
            del args

        def respond(self, body: str, content_type: str = "application/json") -> None:
            encoded = body.encode()
            self.send_response(state.status)
            if 300 <= state.status < 400:
                self.send_header("Location", "/redirected")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            if self.path == "/v1/models":
                self.respond(
                    json.dumps(
                        {
                            "data": [
                                {"id": "llm-model"},
                                {"id": "embedding-model"},
                                {"id": "reranking-model"},
                            ]
                        }
                    )
                )
            elif self.path == "/v1/metrics":
                self.respond("nim_requests_total 1\n", "text/plain")
            else:
                self.respond("{}")

        def do_POST(self) -> None:
            raw_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path == "/v1/chat/completions":
                payload = json.loads(raw_body)
                state.llm_system_prompts.append(payload["messages"][0]["content"])
                self.respond(
                    json.dumps(
                        {
                            "model": "llm-model",
                            "choices": [{"message": {"content": state.llm_content}}],
                        }
                    )
                )
            elif self.path == "/v1/embeddings":
                self.respond(
                    json.dumps(
                        {
                            "model": "embedding-model",
                            "data": [{"embedding": state.embedding}],
                        }
                    )
                )
            elif self.path == "/v1/ranking":
                self.respond(
                    json.dumps(
                        {
                            "model": "reranking-model",
                            "rankings": [
                                {"index": index, "logit": float(2 - position)}
                                for position, index in enumerate(state.ranking_indices)
                            ],
                        }
                    )
                )
            else:
                self.send_error(404)

    return MockNimHandler


@contextmanager
def mock_nim() -> Iterator[tuple[MockNimState, str]]:
    state = MockNimState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield state, f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def run_nim_smoke(
    *,
    kind: str,
    model: str,
    base_url: str,
    home: Path,
    token_file: Path | None = None,
    reasoning_control_mode: str = "llama-standard",
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "NIM_KIND": kind,
            "NIM_BASE_URL": base_url,
            "NIM_MODEL": model,
            "NIM_TIMEOUT_SECONDS": "5",
        }
    )
    environment.pop("NIM_API_KEY", None)
    environment.pop("NIM_API_KEY_FILE", None)
    environment.pop("NIM_API_BASE_URL", None)
    environment.pop("NIM_EMBEDDING_DIMENSION", None)
    environment.pop("NIM_REASONING_CONTROL_MODE", None)
    if kind == "llm":
        environment["NIM_REASONING_CONTROL_MODE"] = reasoning_control_mode
    if kind == "embedding":
        environment["NIM_EMBEDDING_DIMENSION"] = "2"
    if token_file is not None:
        environment["NIM_API_KEY_FILE"] = str(token_file)
    return subprocess.run(
        [str(NIM_SMOKE_SCRIPT)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def run_phase1_smoke(
    *, api_port: int, web_port: int, hostile_proxy: bool = False
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PHASE1_API_PORT": str(api_port),
            "PHASE1_WEB_PORT": str(web_port),
            "PHASE1_SMOKE_TIMEOUT_SECONDS": "45",
        }
    )
    if hostile_proxy:
        environment.update(
            {
                "ALL_PROXY": "http://127.0.0.1:9",
                "HTTP_PROXY": "http://127.0.0.1:9",
                "HTTPS_PROXY": "http://127.0.0.1:9",
                "all_proxy": "http://127.0.0.1:9",
                "http_proxy": "http://127.0.0.1:9",
                "https_proxy": "http://127.0.0.1:9",
            }
        )
        environment.pop("NO_PROXY", None)
        environment.pop("no_proxy", None)

    return subprocess.run(
        [str(PHASE1_SMOKE_SCRIPT)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_preflight_fails_when_output_directory_cannot_be_created() -> None:
    result = subprocess.run(
        [str(PREFLIGHT_SCRIPT), "/proc/ntc-phase1-preflight-test"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode != 0
    assert "Preflight evidence written" not in result.stdout
    assert "Unable to create preflight output directory" in result.stderr


def test_preflight_refuses_to_overwrite_an_existing_evidence_run(
    tmp_path: Path,
) -> None:
    output_directory = tmp_path / "existing-run"
    output_directory.mkdir()
    sentinel = output_directory / "reviewed-evidence.txt"
    sentinel.write_text("keep this evidence\n", encoding="utf-8")

    result = subprocess.run(
        [str(PREFLIGHT_SCRIPT), str(output_directory)],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode != 0
    assert "must not already exist" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "keep this evidence\n"


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep is unavailable")
def test_source_secret_scan_rejects_canary_without_printing_its_value(
    tmp_path: Path,
) -> None:
    sentinel = "nvapi-" + "phase1-canary-credential"
    canary = tmp_path / "leaked-config.env"
    canary.write_text(f'API_KEY="{sentinel}"\n', encoding="utf-8")
    environment = os.environ.copy()
    environment["SOURCE_SECRET_SCAN_ROOT"] = str(tmp_path)

    rejected = subprocess.run(
        [str(SOURCE_SECRET_SCAN_SCRIPT)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert rejected.returncode == 1
    assert "leaked-config.env" in rejected.stderr
    assert sentinel not in rejected.stdout + rejected.stderr

    canary.unlink()
    clean = subprocess.run(
        [str(SOURCE_SECRET_SCAN_SCRIPT)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert clean.returncode == 0, clean.stderr


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep is unavailable")
def test_source_secret_scan_allows_runtime_secret_references(tmp_path: Path) -> None:
    runtime_config = tmp_path / "runtime-config.sh"
    runtime_config.write_text(
        'broker_url="amqp://$user:$password@rabbitmq:5672//"\n',
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["SOURCE_SECRET_SCAN_ROOT"] = str(tmp_path)

    result = subprocess.run(
        [str(SOURCE_SECRET_SCAN_SCRIPT)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not PHASE1_SMOKE_READY, reason="Phase 1 smoke prerequisites unavailable")
def test_phase1_smoke_ignores_hostile_proxy_for_loopback() -> None:
    result = run_phase1_smoke(
        api_port=unused_loopback_port(),
        web_port=unused_loopback_port(),
        hostile_proxy=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Phase 1 smoke passed" in result.stdout


@pytest.mark.skipif(not PHASE1_SMOKE_READY, reason="Phase 1 smoke prerequisites unavailable")
def test_phase1_smoke_rejects_an_occupied_port_before_starting_services() -> None:
    with mock_nim() as (_state, base_url):
        occupied_port = int(base_url.rsplit(":", maxsplit=1)[1])
        result = run_phase1_smoke(
            api_port=occupied_port,
            web_port=unused_loopback_port(),
        )

    assert result.returncode == 2
    assert "PHASE1_API_PORT is already in use" in result.stderr


@pytest.mark.skipif(
    shutil.which("curl") is None or shutil.which("jq") is None,
    reason="curl or jq is unavailable",
)
@pytest.mark.parametrize(
    ("kind", "model"),
    [
        ("llm", "llm-model"),
        ("embedding", "embedding-model"),
        ("reranking", "reranking-model"),
    ],
)
def test_nim_smoke_accepts_valid_2xx_contract_without_loading_curlrc(
    tmp_path: Path,
    kind: str,
    model: str,
) -> None:
    (tmp_path / ".curlrc").write_text("verbose\n", encoding="utf-8")
    token_file = tmp_path / "nim-token"
    token_file.write_text("audit-placeholder-token", encoding="utf-8")

    with mock_nim() as (_state, base_url):
        result = run_nim_smoke(
            kind=kind,
            model=model,
            base_url=base_url,
            home=tmp_path,
            token_file=token_file,
        )

    assert result.returncode == 0, result.stderr
    assert f"{kind} smoke passed" in result.stdout
    assert "Authorization: Bearer" not in result.stdout + result.stderr


@pytest.mark.skipif(
    shutil.which("curl") is None or shutil.which("jq") is None,
    reason="curl or jq is unavailable",
)
def test_nim_smoke_applies_only_allowlisted_candidate_reasoning_controls(
    tmp_path: Path,
) -> None:
    with mock_nim() as (state, base_url):
        llama = run_nim_smoke(
            kind="llm",
            model="llm-model",
            base_url=base_url,
            home=tmp_path,
            reasoning_control_mode="llama-standard",
        )
        nemotron = run_nim_smoke(
            kind="llm",
            model="llm-model",
            base_url=base_url,
            home=tmp_path,
            reasoning_control_mode="nemotron-no-think",
        )
        rejected = run_nim_smoke(
            kind="llm",
            model="llm-model",
            base_url=base_url,
            home=tmp_path,
            reasoning_control_mode="/no_think\nINJECTED",
        )

    assert llama.returncode == 0, llama.stderr
    assert nemotron.returncode == 0, nemotron.stderr
    assert rejected.returncode == 2
    assert state.llm_system_prompts == ["detailed thinking off", "/no_think"]
    assert "INJECTED" not in state.llm_system_prompts


@pytest.mark.skipif(
    shutil.which("curl") is None or shutil.which("jq") is None,
    reason="curl or jq is unavailable",
)
def test_nim_smoke_rejects_redirects(tmp_path: Path) -> None:
    with mock_nim() as (state, base_url):
        state.status = 302
        result = run_nim_smoke(
            kind="llm",
            model="llm-model",
            base_url=base_url,
            home=tmp_path,
        )

    assert result.returncode == 22
    assert "Unexpected HTTP status 302" in result.stderr


@pytest.mark.skipif(
    shutil.which("curl") is None or shutil.which("jq") is None,
    reason="curl or jq is unavailable",
)
def test_nim_smoke_rejects_invalid_llm_and_reranking_responses(
    tmp_path: Path,
) -> None:
    with mock_nim() as (state, base_url):
        state.llm_content = "NOT OK"
        llm_result = run_nim_smoke(
            kind="llm",
            model="llm-model",
            base_url=base_url,
            home=tmp_path,
        )
        state.llm_content = "OK"
        state.ranking_indices = [99, 99]
        reranking_result = run_nim_smoke(
            kind="reranking",
            model="reranking-model",
            base_url=base_url,
            home=tmp_path,
        )

    assert llm_result.returncode != 0
    assert reranking_result.returncode != 0


@pytest.mark.skipif(
    shutil.which("curl") is None or shutil.which("jq") is None,
    reason="curl or jq is unavailable",
)
def test_nim_smoke_rejects_wrong_embedding_dimension_and_reversed_semantics(
    tmp_path: Path,
) -> None:
    with mock_nim() as (state, base_url):
        state.embedding = [0.1]
        embedding_result = run_nim_smoke(
            kind="embedding",
            model="embedding-model",
            base_url=base_url,
            home=tmp_path,
        )
        state.embedding = [0.1, 0.2]
        state.ranking_indices = [1, 0]
        reranking_result = run_nim_smoke(
            kind="reranking",
            model="reranking-model",
            base_url=base_url,
            home=tmp_path,
        )

    assert embedding_result.returncode != 0
    assert reranking_result.returncode != 0
