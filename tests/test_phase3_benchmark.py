from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts import phase3_benchmark as benchmark  # noqa: E402
from scripts.phase3_benchmark import (  # noqa: E402
    DEFAULT_MEASURED_REQUESTS,
    LlmScenario,
    NimBenchmarkClient,
    RunnerConfig,
    SafeBenchmarkError,
    build_llm_prompt,
    execute_benchmark,
    llm_scenarios,
    load_fixtures,
    main,
    percentile,
    write_evidence,
)


class FakeNimState:
    def __init__(self) -> None:
        self.model = "phase3-model"
        self.include_stream_usage = True
        self.include_done_marker = True
        self.reasoning_before_answer = False
        self.http_status = 200
        self.metrics_status = 200
        self.positive_embedding_wins = True
        self.positive_ranking_wins = True
        self.reverse_embedding_items = False
        self.prompt_tokens_override: int | None = None
        self.completion_tokens_override: int | None = None
        self.llm_system_prompts: list[str] = []
        self.llm_user_prompts: list[str] = []
        self.llm_generation_controls: list[dict[str, object]] = []
        self.include_retriever_usage = True
        self.include_retriever_completion_tokens = False


def _handler_for(state: FakeNimState) -> type[BaseHTTPRequestHandler]:
    class FakeNimHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *args: Any) -> None:
            del args

        def _body(self) -> dict[str, object]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            decoded = json.loads(raw)
            assert isinstance(decoded, dict)
            return decoded

        def _send(
            self,
            body: bytes,
            *,
            content_type: str = "application/json",
            status: int | None = None,
        ) -> None:
            self.send_response(state.http_status if status is None else status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: object) -> None:
            self._send(json.dumps(payload).encode())

        def do_GET(self) -> None:
            if self.path in {"/v1/health/live", "/v1/health/ready"}:
                self._json({"status": "ok"})
            elif self.path == "/v1/models":
                self._json({"data": [{"id": state.model}]})
            elif self.path == "/v1/metrics":
                self._send(
                    b"nim_request_total 1\n",
                    content_type="text/plain",
                    status=state.metrics_status,
                )
            else:
                self._json({"error": "not found"})

        def do_POST(self) -> None:
            payload = self._body()
            if self.path == "/v1/chat/completions":
                self._stream_chat(payload)
            elif self.path == "/v1/embeddings":
                self._embedding(payload)
            elif self.path == "/v1/ranking":
                self._ranking(payload)
            else:
                self._json({"error": "not found"})

        def _stream_chat(self, payload: dict[str, object]) -> None:
            max_tokens = payload.get("max_tokens")
            assert isinstance(max_tokens, int) and not isinstance(max_tokens, bool)
            state.llm_generation_controls.append(
                {
                    "max_tokens": max_tokens,
                    "ignore_eos": payload.get("ignore_eos"),
                    "stream": payload.get("stream"),
                }
            )
            messages = payload.get("messages")
            assert isinstance(messages, list) and len(messages) == 2
            system_message = messages[0]
            assert isinstance(system_message, dict)
            system_content = system_message.get("content")
            assert isinstance(system_content, str)
            state.llm_system_prompts.append(system_content)
            user_message = messages[1]
            assert isinstance(user_message, dict)
            user_content = user_message.get("content")
            assert isinstance(user_content, str)
            state.llm_user_prompts.append(user_content)
            prompt_tokens = (
                state.prompt_tokens_override
                if state.prompt_tokens_override is not None
                else user_content.count(" datum") + 125
            )
            completion_tokens = (
                state.completion_tokens_override
                if state.completion_tokens_override is not None
                else max_tokens
            )
            first = (
                "data: "
                + json.dumps(
                    {
                        "model": state.model,
                        "choices": [
                            {
                                "delta": (
                                    {"reasoning_content": "hidden "}
                                    if state.reasoning_before_answer
                                    else {"content": "OK "}
                                )
                            }
                        ],
                    }
                )
                + "\n\n"
            ).encode()
            second_events: list[str] = [
                "data: "
                + json.dumps(
                    {
                        "model": state.model,
                        "choices": [{"delta": {"content": "OK"}}],
                    }
                )
                + "\n\n"
            ]
            if state.include_stream_usage:
                second_events.append(
                    "data: "
                    + json.dumps(
                        {
                            "model": state.model,
                            "choices": [],
                            "usage": {
                                "prompt_tokens": prompt_tokens,
                                "completion_tokens": completion_tokens,
                                "total_tokens": prompt_tokens + completion_tokens,
                            },
                        }
                    )
                    + "\n\n"
                )
            if state.include_done_marker:
                second_events.append("data: [DONE]\n\n")
            second = "".join(second_events).encode()
            body_length = len(first) + len(second)
            self.send_response(state.http_status)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(body_length))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(first)
            self.wfile.flush()
            time.sleep(0.003)
            self.wfile.write(second)
            self.wfile.flush()

        def _embedding(self, payload: dict[str, object]) -> None:
            inputs = payload.get("input")
            assert isinstance(inputs, list)
            vectors: list[list[float]] = []
            for index, item in enumerate(inputs):
                assert isinstance(item, str)
                if "Thủ đô" in item:
                    vector = [1.0, 0.0]
                elif "Hà Nội" in item:
                    vector = [1.0, 0.0] if state.positive_embedding_wins else [0.0, 1.0]
                elif "Tokyo" in item:
                    vector = [0.0, 1.0] if state.positive_embedding_wins else [1.0, 0.0]
                else:
                    vector = [1.0, float(index + 1)]
                vectors.append(vector)
            token_count = len(inputs) * 3
            data = [{"index": index, "embedding": vector} for index, vector in enumerate(vectors)]
            if state.reverse_embedding_items:
                data.reverse()
            response: dict[str, object] = {"model": state.model, "data": data}
            if state.include_retriever_usage:
                usage = {"prompt_tokens": token_count, "total_tokens": token_count}
                if state.include_retriever_completion_tokens:
                    usage["completion_tokens"] = 0
                response["usage"] = usage
            self._json(response)

        def _ranking(self, payload: dict[str, object]) -> None:
            passages = payload.get("passages")
            assert isinstance(passages, list)
            rankings = [
                {"index": index, "logit": float(len(passages) - index)}
                for index in range(len(passages))
            ]
            if not state.positive_ranking_wins and len(rankings) == 2:
                rankings[0]["logit"] = 0.0
                rankings[1]["logit"] = 2.0
            response: dict[str, object] = {"model": state.model, "rankings": rankings}
            if state.include_retriever_usage:
                token_count = len(passages) * 4
                usage = {"prompt_tokens": token_count, "total_tokens": token_count}
                if state.include_retriever_completion_tokens:
                    usage["completion_tokens"] = 0
                response["usage"] = usage
            self._json(response)

    return FakeNimHandler


@contextmanager
def fake_nim() -> Iterator[tuple[FakeNimState, str]]:
    state = FakeNimState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _config(kind: str, base_url: str, **overrides: object) -> RunnerConfig:
    values: dict[str, object] = {
        "kind": kind,
        "base_url": base_url,
        "model": "phase3-model",
        "candidate_id": f"candidate-{kind}",
        "measured_requests": 1,
        "warmup_requests": 0,
        "timeout_seconds": 5.0,
        "metrics_required": kind == "llm",
        "include_long_context": False,
        "seed": 17,
        "image_ref": None,
        "image_digest": None,
        "nim_version": None,
        "runtime_profile": None,
        "precision": None,
        "max_model_length": None,
        "license_id": None,
        "reasoning_control_mode": "llama-standard" if kind == "llm" else None,
    }
    values.update(overrides)
    return RunnerConfig(**values)  # type: ignore[arg-type]


def test_fixed_scenarios_and_fixture_generation_are_deterministic() -> None:
    fixtures = load_fixtures()
    default_names = [scenario.name for scenario in llm_scenarios(False)]
    long_scenarios = llm_scenarios(True)

    assert DEFAULT_MEASURED_REQUESTS == 20
    assert default_names == ["engine-short-c1", "rag-8k-c1", "rag-8k-c4"]
    assert [scenario.target_context_tokens for scenario in long_scenarios[-3:]] == [
        32_768,
        65_536,
        131_072,
    ]
    scenario = LlmScenario("test", "short", 512, 256, 1)
    assert build_llm_prompt(fixtures, scenario) == build_llm_prompt(fixtures, scenario)
    assert len(fixtures.sha256) == 64
    assert not fixtures.llm_system.startswith(("detailed thinking off", "/no_think"))


def test_llm_requests_use_disjoint_nonpersisted_nonces_before_shared_context() -> None:
    fixtures = load_fixtures()
    with fake_nim() as (state, base_url):
        report, _metrics = execute_benchmark(
            _config(
                "llm",
                base_url,
                measured_requests=2,
                warmup_requests=2,
            ),
            fixtures,
        )

    assert len(state.llm_user_prompts) == 12
    assert len(set(state.llm_user_prompts)) == 12
    assert all(prompt.startswith("synthetic_request_nonce=") for prompt in state.llm_user_prompts)
    nonce_values = [prompt.split("\n", 1)[0].split("=", 1)[1] for prompt in state.llm_user_prompts]
    assert all(len(value) == 64 for value in nonce_values)
    run_config = report["run_config"]
    assert isinstance(run_config, dict)
    assert run_config["llm_prompt_uniqueness_control"] == {
        "status": "enabled",
        "nonce_position": "first_user_content_line_before_synthetic_context",
        "nonce_derivation": "sha256(scenario_name|request_phase|request_index)",
        "warmup_and_measured_namespaces_disjoint": True,
        "full_user_prompt_reuse_between_requests": False,
        "nonce_persisted": False,
    }
    serialized = json.dumps(report)
    assert all(value not in serialized for value in nonce_values)


def test_llm_reasoning_control_is_allowlisted_candidate_specific_and_reported() -> None:
    fixtures = load_fixtures()
    with fake_nim() as (state, base_url):
        llama_report, _ = execute_benchmark(
            _config("llm", base_url, reasoning_control_mode="llama-standard"), fixtures
        )
        nemotron_report, _ = execute_benchmark(
            _config("llm", base_url, reasoning_control_mode="nemotron-no-think"), fixtures
        )

    assert state.llm_system_prompts[:3] == [f"detailed thinking off\n\n{fixtures.llm_system}"] * 3
    assert state.llm_system_prompts[3:] == [f"/no_think\n\n{fixtures.llm_system}"] * 3
    llama_run_config = llama_report["run_config"]
    nemotron_run_config = nemotron_report["run_config"]
    assert isinstance(llama_run_config, dict) and isinstance(nemotron_run_config, dict)
    assert llama_run_config["reasoning_control_mode"] == "llama-standard"
    assert nemotron_run_config["reasoning_control_mode"] == "nemotron-no-think"
    assert llama_report["schema_version"] == 2
    assert nemotron_report["schema_version"] == 2
    assert llama_run_config["system_prompt_persisted"] is False
    serialized = json.dumps([llama_report, nemotron_report])
    assert fixtures.llm_system not in serialized
    assert "detailed thinking off" not in serialized
    assert "/no_think" not in serialized


@pytest.mark.parametrize(
    ("kind", "mode", "error"),
    [
        ("llm", None, "invalid_reasoning_control_mode"),
        ("llm", "raw prompt injection", "invalid_reasoning_control_mode"),
        ("embedding", "llama-standard", "reasoning_control_not_applicable"),
    ],
)
def test_invalid_reasoning_control_is_rejected_before_network(
    kind: str, mode: object, error: str
) -> None:
    with pytest.raises(SafeBenchmarkError, match=error):
        execute_benchmark(
            _config(kind, "http://127.0.0.1:9/v1", reasoning_control_mode=mode),
            load_fixtures(),
        )


def test_percentile_uses_documented_linear_interpolation() -> None:
    assert percentile([], 0.5) is None
    assert percentile([4.0], 0.95) == 4.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.95) == pytest.approx(3.85)


def test_llm_stream_metrics_use_response_usage_and_stream_timestamps() -> None:
    fixtures = load_fixtures()
    with (
        fake_nim() as (state, base_url),
        NimBenchmarkClient(
            base_url=base_url,
            model="phase3-model",
            timeout_seconds=5,
        ) as client,
    ):
        assert client.contract_check(metrics_required=True)["status"] == "pass"
        metric = client.measure_llm(
            scenario=LlmScenario("engine-test", "short", 512, 256, 1),
            request_index=0,
            fixtures=fixtures,
            seed=17,
        )

    assert metric.status == "ok"
    assert metric.prompt_tokens_actual == 509
    assert metric.completion_tokens_actual == 256
    assert metric.total_tokens_actual == 765
    assert metric.ttft_seconds is not None and metric.ttft_seconds > 0
    assert metric.decode_duration_seconds is not None and metric.decode_duration_seconds > 0
    assert metric.decode_tokens_per_second == pytest.approx(256 / metric.decode_duration_seconds)
    assert metric.total_latency_seconds is not None
    assert metric.total_latency_seconds >= metric.ttft_seconds
    assert state.llm_generation_controls == [
        {"max_tokens": 256, "ignore_eos": True, "stream": True}
    ]


def test_llm_output_token_mismatch_is_a_failed_measurement() -> None:
    fixtures = load_fixtures()
    with fake_nim() as (state, base_url):
        state.completion_tokens_override = 63
        with NimBenchmarkClient(
            base_url=base_url,
            model="phase3-model",
            timeout_seconds=5,
        ) as client:
            metric = client.measure_llm(
                scenario=LlmScenario("engine-test", "short", 512, 64, 1),
                request_index=0,
                fixtures=fixtures,
                seed=17,
            )

    assert metric.status == "failed"
    assert metric.error_code == "output_token_target_mismatch"
    assert metric.completion_tokens_actual == 63
    assert metric.max_output_tokens == 64
    assert metric.decode_tokens_per_second is None


def test_llm_missing_usage_fails_without_estimating_tokens() -> None:
    fixtures = load_fixtures()
    with fake_nim() as (state, base_url):
        state.include_stream_usage = False
        with NimBenchmarkClient(
            base_url=base_url,
            model="phase3-model",
            timeout_seconds=5,
        ) as client:
            metric = client.measure_llm(
                scenario=LlmScenario("engine-test", "short", 512, 256, 1),
                request_index=0,
                fixtures=fixtures,
                seed=17,
            )

    assert metric.status == "failed"
    assert metric.error_code == "missing_actual_usage"
    assert metric.prompt_tokens_actual is None
    assert metric.completion_tokens_actual is None
    assert metric.decode_tokens_per_second is None


def test_llm_usage_parser_still_requires_all_three_consistent_counts() -> None:
    with pytest.raises(SafeBenchmarkError, match="invalid_usage_token_counts"):
        benchmark._llm_usage({"usage": {"prompt_tokens": 8, "total_tokens": 8}})
    with pytest.raises(SafeBenchmarkError, match="inconsistent_usage_token_totals"):
        benchmark._llm_usage(
            {
                "usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": 2,
                    "total_tokens": 9,
                }
            }
        )


def test_llm_stream_without_done_marker_is_not_accepted_as_complete() -> None:
    fixtures = load_fixtures()
    with fake_nim() as (state, base_url):
        state.include_done_marker = False
        with NimBenchmarkClient(
            base_url=base_url,
            model="phase3-model",
            timeout_seconds=5,
        ) as client:
            metric = client.measure_llm(
                scenario=LlmScenario("engine-test", "short", 512, 256, 1),
                request_index=0,
                fixtures=fixtures,
                seed=17,
            )

    assert metric.status == "failed"
    assert metric.error_code == "missing_stream_done_marker"


def test_llm_metrics_include_hidden_reasoning_in_token_timing_without_persisting_it() -> None:
    fixtures = load_fixtures()
    with fake_nim() as (state, base_url):
        state.reasoning_before_answer = True
        with NimBenchmarkClient(
            base_url=base_url,
            model="phase3-model",
            timeout_seconds=5,
        ) as client:
            metric = client.measure_llm(
                scenario=LlmScenario("engine-test", "short", 512, 256, 1),
                request_index=0,
                fixtures=fixtures,
                seed=17,
            )

    assert metric.status == "ok"
    assert metric.decode_duration_seconds is not None
    assert metric.decode_duration_seconds > 0
    assert "hidden" not in repr(metric)


def test_llm_scenario_fails_when_actual_prompt_tokens_miss_the_declared_target() -> None:
    fixtures = load_fixtures()
    with fake_nim() as (state, base_url):
        state.prompt_tokens_override = 100
        report, _metrics = execute_benchmark(_config("llm", base_url), fixtures)

    assert report["status"] == "fail"
    scenarios = report["scenarios"]
    assert isinstance(scenarios, list)
    for scenario in scenarios:
        assert scenario["summary"]["status"] == "fail"
        assert scenario["summary"]["input_token_target_check"]["status"] == "fail"


def test_long_context_gate_uses_absolute_prompt_plus_output_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_context = 32_768
    max_output = 64
    scenario = LlmScenario(
        "long-32k-c1",
        "long",
        32_448,
        max_output,
        1,
        target_context,
    )
    monkeypatch.setattr(benchmark, "llm_scenarios", lambda _include: (scenario,))
    fixtures = load_fixtures()
    with fake_nim() as (state, base_url):
        state.prompt_tokens_override = target_context - max_output - 512
        boundary_report, _ = execute_benchmark(
            _config("llm", base_url, include_long_context=True, warmup_requests=1), fixtures
        )
        state.prompt_tokens_override = target_context - max_output - 513
        outside_report, _ = execute_benchmark(
            _config("llm", base_url, include_long_context=True, warmup_requests=1), fixtures
        )

    boundary_check = boundary_report["scenarios"][0]["summary"]["input_token_target_check"]
    assert boundary_report["status"] == "pass"
    assert boundary_check["required_relation"] == (
        "every_observed_prompt_plus_max_output_within_absolute_context_window"
    )
    assert boundary_check["absolute_context_lower_bound"] == target_context - 512
    assert boundary_check["absolute_context_upper_bound"] == target_context
    assert boundary_check["observed_prompt_plus_max_output_min"] == target_context - 512
    assert outside_report["status"] == "fail"
    assert outside_report["scenarios"][0]["summary"]["input_token_target_check"]["status"] == "fail"


def test_llm_report_requires_exact_output_target_for_measured_and_warmup_requests() -> None:
    fixtures = load_fixtures()
    with fake_nim() as (state, base_url):
        state.completion_tokens_override = 17
        report, metrics = execute_benchmark(
            _config("llm", base_url, measured_requests=1, warmup_requests=1), fixtures
        )

    assert report["status"] == "fail"
    assert len(metrics) == 3
    assert all(metric.error_code == "output_token_target_mismatch" for metric in metrics)
    scenarios = report["scenarios"]
    assert isinstance(scenarios, list)
    for scenario in scenarios:
        check = scenario["summary"]["output_token_target_check"]
        assert check["status"] == "fail"
        assert check["required_relation"] == ("completion_tokens_actual_equals_max_output_tokens")
        assert check["fixed_request_control"] == {
            "ignore_eos": True,
            "scope": "synthetic_llm_benchmark_only",
        }
        assert check["measured"] == {
            "required_count": 1,
            "observed_count": 1,
            "matching_count": 0,
            "observed_min": 17,
            "observed_max": 17,
        }
        assert check["warmup"] == {
            "required_count": 1,
            "observed_count": 1,
            "matching_count": 0,
            "observed_min": 17,
            "observed_max": 17,
        }


def test_llm_report_defines_fixed_output_length_comparability_control() -> None:
    with fake_nim() as (_state, base_url):
        report, _metrics = execute_benchmark(_config("llm", base_url), load_fixtures())

    definitions = report["metric_definitions"]
    assert isinstance(definitions, dict)
    output_definition = definitions["output_token_target_check"]
    assert isinstance(output_definition, str)
    assert "ignore_eos=true" in output_definition
    assert "every warmup and measured" in output_definition
    assert "exactly equal" in output_definition
    assert "not used by smoke or quality" in output_definition
    uniqueness_definition = definitions["prompt_uniqueness_control"]
    assert isinstance(uniqueness_definition, str)
    assert "SHA-256 nonce" in uniqueness_definition
    assert "warmup and measured namespaces are disjoint" in uniqueness_definition
    assert "full user prompts are not reused" in uniqueness_definition


def test_fixed_ignore_eos_control_is_confined_to_synthetic_llm_benchmark() -> None:
    for relative_path in ("scripts/phase3_quality.py", "scripts/nim-smoke.sh"):
        source = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        assert "ignore_eos" not in source


@pytest.mark.parametrize("kind", ["embedding", "reranking"])
def test_embedding_and_reranking_modes_are_semantic_sanity_not_phase5(
    kind: str,
) -> None:
    fixtures = load_fixtures()
    with fake_nim() as (state, base_url):
        state.metrics_status = 404
        report, metrics = execute_benchmark(_config(kind, base_url), fixtures)

    assert report["status"] == "pass"
    semantic = report["semantic_check"]
    assert isinstance(semantic, dict)
    assert semantic["status"] == "pass"
    assert semantic["quality_scope"] == "basic_semantic_sanity_only_not_phase5_retrieval_eval"
    contract = report["contract_check"]
    assert isinstance(contract, dict)
    assert "metrics_non_empty" not in contract
    assert contract["metrics"] == {
        "required": False,
        "status": "unsupported",
        "http_status": 404,
        "non_empty": False,
        "probe_error_code": None,
    }
    run_config = report["run_config"]
    assert isinstance(run_config, dict)
    assert run_config["llm_prompt_uniqueness_control"] == {"status": "not_applicable"}
    assert len(metrics) == 2
    assert all(metric.status == "ok" for metric in metrics)
    assert all(metric.prompt_tokens_actual is not None for metric in metrics)
    assert all(metric.completion_tokens_actual is None for metric in metrics)
    assert all(metric.total_tokens_actual is not None for metric in metrics)
    scenarios = report["scenarios"]
    assert isinstance(scenarios, list) and len(scenarios) == 2


@pytest.mark.parametrize("kind", ["embedding", "reranking"])
def test_retriever_modes_accept_omitted_usage_without_estimating_tokens(kind: str) -> None:
    fixtures = load_fixtures()
    with fake_nim() as (state, base_url):
        state.include_retriever_usage = False
        report, metrics = execute_benchmark(_config(kind, base_url), fixtures)

    assert report["status"] == "pass"
    assert all(metric.status == "ok" for metric in metrics)
    assert all(metric.prompt_tokens_actual is None for metric in metrics)
    assert all(metric.completion_tokens_actual is None for metric in metrics)
    assert all(metric.total_tokens_actual is None for metric in metrics)


def test_retriever_usage_preserves_optional_completion_and_rejects_bad_counts() -> None:
    without_completion = benchmark._retriever_usage(
        {"usage": {"prompt_tokens": 8, "total_tokens": 8}}
    )
    with_completion = benchmark._retriever_usage(
        {
            "usage": {
                "prompt_tokens": 8,
                "completion_tokens": 0,
                "total_tokens": 8,
            }
        }
    )

    assert without_completion is not None
    assert without_completion.completion_tokens is None
    assert with_completion is not None
    assert with_completion.completion_tokens == 0
    with pytest.raises(SafeBenchmarkError, match="invalid_usage_token_counts"):
        benchmark._retriever_usage(
            {"usage": {"prompt_tokens": 8, "completion_tokens": "0", "total_tokens": 8}}
        )
    with pytest.raises(SafeBenchmarkError, match="inconsistent_usage_token_totals"):
        benchmark._retriever_usage({"usage": {"prompt_tokens": 8, "total_tokens": 9}})


def test_embedding_mode_uses_response_indices_instead_of_wire_order() -> None:
    fixtures = load_fixtures()
    with fake_nim() as (state, base_url):
        state.reverse_embedding_items = True
        report, metrics = execute_benchmark(_config("embedding", base_url), fixtures)

    assert report["status"] == "pass"
    semantic_check = report["semantic_check"]
    assert isinstance(semantic_check, dict)
    assert semantic_check["status"] == "pass"
    assert all(metric.status == "ok" for metric in metrics)


def test_llm_metrics_endpoint_remains_a_required_contract() -> None:
    with fake_nim() as (state, base_url):
        state.metrics_status = 404
        with (
            NimBenchmarkClient(
                base_url=base_url,
                model="phase3-model",
                timeout_seconds=5,
            ) as client,
            pytest.raises(SafeBenchmarkError, match="http_404_metrics"),
        ):
            client.contract_check(metrics_required=True)


def test_report_keeps_runtime_metadata_unverified_and_excludes_secrets_and_url(
    tmp_path: Path,
) -> None:
    fixtures = load_fixtures()
    secret = "phase3-private-token-value"
    with fake_nim() as (_state, base_url):
        report, metrics = execute_benchmark(
            _config(
                "llm",
                base_url,
                measured_requests=1,
                runtime_profile=None,
                precision=None,
            ),
            fixtures,
            api_key=secret,
        )

    serialized = json.dumps(report)
    assert secret not in serialized
    assert base_url not in serialized
    runtime = report["runtime"]
    assert isinstance(runtime, dict)
    assert runtime["profile"] == {"value": None, "evidence_source": "unverified"}
    assert runtime["precision"] == {"value": None, "evidence_source": "unverified"}

    output_directory = tmp_path / "evidence"
    write_evidence(output_directory, report, metrics)
    persisted = (output_directory / "report.json").read_text(encoding="utf-8")
    persisted += (output_directory / "requests.csv").read_text(encoding="utf-8")
    assert secret not in persisted
    assert base_url not in persisted
    assert fixtures.llm_system not in persisted
    assert len(metrics) == 3
    with pytest.raises(SafeBenchmarkError, match="output_directory_already_exists"):
        write_evidence(output_directory, report, metrics)


def test_evidence_write_failure_never_publishes_a_partial_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixtures = load_fixtures()
    with fake_nim() as (_state, base_url):
        report, metrics = execute_benchmark(_config("llm", base_url), fixtures)
    output_directory = tmp_path / "atomic-benchmark"

    def fail_csv(_path: Path, _metrics: object) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(benchmark, "_write_csv_synced", fail_csv)
    with pytest.raises(SafeBenchmarkError, match="evidence_write_failed"):
        write_evidence(output_directory, report, metrics)

    assert not output_directory.exists()
    assert not (tmp_path / ".atomic-benchmark.lock").exists()
    assert not list(tmp_path.glob(".atomic-benchmark.tmp-*"))


def test_cli_rejects_url_userinfo_without_echoing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "do-not-echo-this-secret"
    result = main(
        [
            "--kind",
            "llm",
            "--base-url",
            f"http://user:{secret}@127.0.0.1:8000/v1",
            "--model",
            "phase3-model",
            "--candidate-id",
            "candidate-llm",
            "--output-dir",
            str(tmp_path / "evidence"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "base_url_userinfo_forbidden" in captured.err
    assert secret not in captured.out + captured.err
    assert not (tmp_path / "evidence").exists()


def test_live_contract_failure_writes_secret_safe_failure_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "phase3-file-secret-never-persist"
    token_file = tmp_path / "token"
    token_file.write_text(secret + "\n", encoding="utf-8")
    output_directory = tmp_path / "failed-run"
    with fake_nim() as (state, base_url):
        state.http_status = 503
        result = main(
            [
                "--kind",
                "llm",
                "--base-url",
                base_url,
                "--model",
                "phase3-model",
                "--candidate-id",
                "candidate-llm",
                "--reasoning-control-mode",
                "llama-standard",
                "--api-key-file",
                str(token_file),
                "--output-dir",
                str(output_directory),
                "--requests",
                "1",
                "--warmup",
                "0",
            ]
        )

    captured = capsys.readouterr()
    report_text = (output_directory / "report.json").read_text(encoding="utf-8")
    csv_text = (output_directory / "requests.csv").read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert result == 1
    assert report["status"] == "fail"
    assert report["failure"]["error_code"] == "http_503_health_live"
    assert secret not in report_text + csv_text + captured.out + captured.err
    assert base_url not in report_text + csv_text
