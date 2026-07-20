#!/usr/bin/env python3
"""Run a real web_search evaluation set and write report artifacts.

The script intentionally exercises the LangGraph workflow directly instead of
mocking provider calls. It adds temporary allow-domain rules to test source
policy behavior, then removes only the rules it created.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
OUT_DIR = ROOT / "tests" / "test-websearch"
TEMP_DOMAINS = [
    "chinhphu.vn",
    "chatgpt.com",
    "github.com",
    "moh.gov.vn",
    "who.int",
    "openai.com",
    "docs.langchain.com",
    "langchain-ai.github.io",
    "vnexpress.net",
    "vietnamplus.vn",
    "myvietnamtours.com",
    "thuvienphapluat.vn",
    "luatvietnam.vn",
    "tratu.soha.vn",
    "vnptai.io",
    "200lab.io",
    "ibm.com",
    "webgia.com",
    "thegioibang.com",
    "thitruonghanghoa.com",
]

QUESTIONS = [
    "ntcai là gì, bạn tóm tắt công ty này làm gì là được.",
    "site:ntcai.vn NTC AI cung cấp những nhóm giải pháp AI nào?",
    "Giá xăng RON95 hôm nay tại Việt Nam là bao nhiêu và nguồn nào công bố?",
    "Chính phủ Việt Nam hiện quy định thời hạn thị thực điện tử như thế nào?",
    "WHO khuyến cáo phòng bệnh sốt xuất huyết như thế nào?",
    "OpenAI GPT-4.1 là gì và phù hợp cho những tác vụ nào?",
    "LangGraph là gì và nó dùng để xây workflow agent như thế nào?",
    "Mức lương tối thiểu vùng Việt Nam hiện nay là bao nhiêu?",
    "RAG là gì trong AI, giải thích ngắn gọn và nêu lợi ích chính.",
    "nhattienchung.vn là công ty gì, tóm tắt ngắn gọn.",
]


def load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)


def ensure_backend_path() -> None:
    sys.path.insert(0, str(BACKEND_DIR))


async def add_temp_domains() -> list[int]:
    from database.setup_postgres import SessionLocal
    from database.table.table_postgres import WebSourceRule
    from sqlalchemy import select

    created_ids: list[int] = []
    async with SessionLocal() as db:
        for domain in TEMP_DOMAINS:
            exists = await db.execute(
                select(WebSourceRule.id).where(
                    WebSourceRule.rule_type == "allow",
                    WebSourceRule.match_type == "domain",
                    WebSourceRule.value == domain,
                )
            )
            if exists.scalar_one_or_none() is not None:
                continue
            item = WebSourceRule(
                rule_type="allow",
                match_type="domain",
                value=domain,
                note="temporary web_search evaluation domain",
                is_active=True,
            )
            db.add(item)
            await db.flush()
            created_ids.append(int(item.id))
        await db.commit()

    await invalidate_policy_cache()
    return created_ids


async def cleanup_temp_domains(created_ids: list[int]) -> None:
    if not created_ids:
        return

    from database.setup_postgres import SessionLocal
    from database.table.table_postgres import WebSourceRule

    async with SessionLocal() as db:
        for rule_id in created_ids:
            item = await db.get(WebSourceRule, rule_id)
            if item:
                await db.delete(item)
        await db.commit()

    await invalidate_policy_cache()


async def invalidate_policy_cache() -> None:
    from agent_chatbot.node.util.rag_query_util import invalidate_web_source_policy_cache

    await invalidate_web_source_policy_cache()


def base_state(question: str, model_name: str) -> dict[str, Any]:
    return {
        "user_id": "websearch-eval",
        "session_id": -1,
        "user_input": question,
        "model_name": model_name,
        "query_flow": "web_search",
        "web_urls": [],
        "web_mode": "open_web",
        "path_list": [],
        "search_results": [],
        "filtered_paths": [],
        "context_with_path": [],
        "assistant_response": "",
        "sse_queue": None,
        "web_loop_iteration": 0,
        "web_should_retry": False,
        "web_retry_reasons": [],
    }


async def run_question(idx: int, question: str, model_name: str) -> dict[str, Any]:
    from agent_chatbot.graph.rag_graph import app_rag_web_search_workflow

    started = time.perf_counter()
    result = await app_rag_web_search_workflow.ainvoke(base_state(question, model_name))
    elapsed = round(time.perf_counter() - started, 2)

    answer = (result.get("assistant_response") or "").strip()
    evidence = result.get("reranked_evidence") or []
    verify = result.get("web_verify_debug") or {}
    search_debug = result.get("web_search_debug") or {}
    fetch_debug = result.get("web_fetch_debug") or {}

    fallback_markers = [
        "chưa thu thập được bằng chứng web đủ tin cậy",
        "web search tạm thời lỗi",
        "chưa cấu hình provider tìm kiếm web",
    ]
    passed = bool(answer) and bool(evidence) and not any(m in answer.lower() for m in fallback_markers)
    if verify and verify.get("citation_ok") is False:
        passed = False

    return {
        "index": idx,
        "question": question,
        "passed": passed,
        "elapsed_sec": elapsed,
        "confidence": result.get("confidence") or "n/a",
        "answer": answer,
        "answer_preview": answer[:900],
        "selected_urls": result.get("selected_urls") or [],
        "evidence_count": len(evidence),
        "evidence": [
            {
                "url": ev.get("url"),
                "title": ev.get("title"),
                "score": ev.get("score"),
                "source_score": ev.get("source_score"),
            }
            for ev in evidence
        ],
        "search_debug": {
            "candidate_count": search_debug.get("candidate_count"),
            "domain_policy_mode": search_debug.get("domain_policy_mode"),
            "preferred_domains": search_debug.get("preferred_domains"),
            "restrict_to_target_domains": search_debug.get("restrict_to_target_domains"),
            "search_issue": search_debug.get("search_issue"),
            "provider_name_counts": search_debug.get("provider_name_counts"),
        },
        "fetch_debug": fetch_debug,
        "verify_debug": verify,
    }


def write_markdown(report_path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Web Search Evaluation Report",
        "",
        f"- Thời gian: {payload['generated_at']}",
        f"- Model: `{payload['model_name']}`",
        f"- Kết quả: {payload['passed_count']}/{payload['total']} pass",
        f"- Domain tạm đã thêm: {', '.join(payload['temp_domains'])}",
        f"- Cleanup domain tạm: {'done' if payload['cleanup_done'] else 'not-run'}",
        "",
        "## Câu hỏi và câu trả lời",
        "",
    ]

    for item in payload["results"]:
        lines.extend(
            [
                f"### {item['index']}. {'PASS' if item['passed'] else 'FAIL'}",
                "",
                f"**Câu hỏi:** {item['question']}",
                "",
                f"**Thời gian:** {item['elapsed_sec']}s",
                "",
                f"**Confidence:** {item['confidence']}",
                "",
                "**Câu trả lời:**",
                "",
                item["answer"] or "(empty)",
                "",
                "**Nguồn/evidence:**",
            ]
        )
        for ev in item["evidence"]:
            lines.append(f"- {ev.get('url')} (score={ev.get('score')})")
        lines.extend(
            [
                "",
                "**Debug ngắn:**",
                "",
                "```json",
                json.dumps(
                    {
                        "search": item["search_debug"],
                        "fetch": item["fetch_debug"],
                        "verify": item["verify_debug"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
            ]
        )

    report_path.write_text("\n".join(lines), encoding="utf-8")


def make_png_evidence(image_path: Path, payload: dict[str, Any]) -> None:
    from PIL import Image, ImageDraw, ImageFont

    def font_file(*candidates: str) -> str | None:
        for candidate in candidates:
            if Path(candidate).exists():
                return candidate
        return None

    width = 1800
    margin = 48
    line_height = 31
    rows: list[tuple[str, str]] = []
    rows.append(("title", "Web Search Evaluation"))
    rows.append(("meta", f"{payload['generated_at']} | PASS {payload['passed_count']}/{payload['total']} | cleanup={'done' if payload['cleanup_done'] else 'not-run'}"))
    rows.append(("meta", f"Artifacts: {payload['json_path']} | {payload['markdown_path']}"))
    for item in payload["results"]:
        status = "PASS" if item["passed"] else "FAIL"
        urls = ", ".join((ev.get("url") or "") for ev in item["evidence"][:2]) or "no evidence"
        rows.append(("question", f"{item['index']}. {status} | {item['question']}"))
        preview = " ".join((item["answer_preview"] or "").split())
        rows.append(("answer", f"Answer: {preview}"))
        rows.append(("source", f"Sources: {urls}"))

    wrapped_lines: list[tuple[str, str]] = []
    for kind, text in rows:
        wrap_width = 95 if kind in {"answer", "source"} else 110
        for line in textwrap.wrap(text, width=wrap_width) or [""]:
            wrapped_lines.append((kind, line))

    height = margin * 2 + (len(wrapped_lines) + 2) * line_height
    image = Image.new("RGB", (width, height), "#f7fafc")
    draw = ImageDraw.Draw(image)

    font_path = font_file(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/liberation-sans/LiberationSans-Regular.ttf",
    )
    bold_path = font_file(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/liberation-sans/LiberationSans-Bold.ttf",
    )
    if font_path and bold_path:
        font = ImageFont.truetype(font_path, 24)
        small = ImageFont.truetype(font_path, 22)
        bold = ImageFont.truetype(bold_path, 26)
        title_font = ImageFont.truetype(bold_path, 40)
    else:
        font = ImageFont.load_default()
        small = font
        bold = font
        title_font = font

    y = margin
    for kind, line in wrapped_lines:
        if kind == "title":
            draw.text((margin, y), line, fill="#111827", font=title_font)
            y += line_height + 22
            continue
        if kind == "meta":
            draw.text((margin, y), line, fill="#475569", font=small)
        elif kind == "question":
            draw.rounded_rectangle((margin - 12, y - 5, width - margin, y + line_height + 4), radius=8, fill="#e0f2fe")
            draw.text((margin, y), line, fill="#0f172a", font=bold)
        elif kind == "source":
            draw.text((margin, y), line, fill="#0369a1", font=small)
        else:
            draw.text((margin, y), line, fill="#1f2937", font=font)
        y += line_height

    image.save(image_path)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.getenv("VLLM_MODEL_NAME", "google/gemma-4-E4B-it"))
    args = parser.parse_args()

    load_env()
    ensure_backend_path()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    evidence_dir = OUT_DIR / "evidence" / stamp
    evidence_dir.mkdir(parents=True, exist_ok=True)

    created_ids: list[int] = []
    cleanup_done = False
    results: list[dict[str, Any]] = []
    try:
        created_ids = await add_temp_domains()
        for idx, question in enumerate(QUESTIONS, 1):
            print(f"[{idx}/{len(QUESTIONS)}] {question}", flush=True)
            results.append(await run_question(idx, question, args.model))
    finally:
        await cleanup_temp_domains(created_ids)
        cleanup_done = True

    passed_count = sum(1 for item in results if item["passed"])
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model_name": args.model,
        "total": len(results),
        "passed_count": passed_count,
        "temp_domains": TEMP_DOMAINS,
        "created_domain_rule_ids": created_ids,
        "cleanup_done": cleanup_done,
        "results": results,
    }

    json_path = evidence_dir / "websearch-results.json"
    md_path = evidence_dir / "websearch-report.md"
    png_path = evidence_dir / "websearch-evidence.png"
    payload["json_path"] = str(json_path.relative_to(ROOT))
    payload["markdown_path"] = str(md_path.relative_to(ROOT))
    payload["png_path"] = str(png_path.relative_to(ROOT))

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(md_path, payload)
    make_png_evidence(png_path, payload)

    latest_json = OUT_DIR / "latest-results.json"
    latest_md = OUT_DIR / "latest-report.md"
    latest_png = OUT_DIR / "latest-evidence.png"
    latest_json.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
    latest_md.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    latest_png.write_bytes(png_path.read_bytes())

    print(f"PASS {passed_count}/{len(results)}")
    print(f"REPORT {md_path}")
    print(f"IMAGE {png_path}")
    return 0 if passed_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
