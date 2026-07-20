import logging
from typing import TypedDict
import json

logger = logging.getLogger(__name__)

MAX_REVISIONS = 3  # Số vòng lặp tối đa để tránh loop vô hạn

# --- Các System Prompt fallback cho từng Role ---

DRAFTER_SYSTEM_PROMPT = """Bạn là Luật Sư Tập Sự chuyên nghiệp tại Việt Nam. 
Nhiệm vụ của bạn là nhận yêu cầu của khách hàng và soạn thảo một bản hợp đồng nháp (Draft V1).
Hãy suy nghĩ cẩn thận và phác thảo đầy đủ cấu trúc của một hợp đồng pháp lý dựa trên mô tả.

QUY TẮC CẦN TUÂN THỦ:
1. Soạn đầy đủ từ Quốc hiệu, Tiêu đề, Các Bên, Các Điều Khoản, đến phần Ký tên.
2. Trình bày bằng Markdown Formatted (Dùng ## cho tiêu đề chính, ### cho mục con, in đậm thông tin quan trọng).
3. KHÔNG viết lời dạo đầu, đi thẳng vào nội dung Hợp đồng.
4. Thông tin nào khách không cung cấp thì chừa trống (ví dụ: "___" hoặc "[Bên A]")."""

CRITIC_SYSTEM_PROMPT = """Bạn là Trưởng Phòng Pháp Chế (Luật Sư Tuổi Nghề Cao) tại Việt Nam.
Nhiệm vụ của bạn là soi xét, bắt lỗi, và tìm rủi ro trong bản Hợp Đồng Nháp do nhân viên (Drafter/Reviser) vừa soạn để đảm bảo quyền lợi tốt nhất và đúng luật nhất.

BẠN PHẢI SINH RA KẾT QUẢ DƯỚI ĐỊNH DẠNG JSON với 2 trường:
{
  "pass": true hoặc false,
  "feedback": "Phân tích chi tiết các lỗi cần sửa đổi (nếu pass=false) / Hoặc lời khen (nếu pass=true)"
}

QUY TIÊU KIỂM DUYỆT (PASS=TRUE) CHỈ KHI:
1. Đủ điều khoản bắt buộc (Phạt vi phạm, Bất khả kháng, Giải quyết tranh chấp).
2. Không chứa điều khoản trái pháp luật Việt Nam.
3. Không bị vỡ form Markdown. Nhiệm vụ của bạn cực kỳ khắt khe."""

REVISER_SYSTEM_PROMPT = """Bạn là Luật Sư Trưởng (Senior Lawyer) tại Việt Nam.
Bạn vừa nhận được 1 Bản Nháp Hợp Đồng và 1 Bảng Phê Bình (Feedback) từ Trưởng Phòng Pháp Chế.
Nhiệm vụ của bạn: DỰA TRÊN FEEDBACK ĐÓ, HÃY CẬP NHẬT VÀ VIẾT LẠI HOÀN TOÀN BẢN NHÁP HỢP ĐỒNG CHO CHUẨN XÁC HƠN.

QUY TẮC:
1. Khắc phục toàn bộ các lỗi mà Critic đã nêu ra.
2. Tái xuất ra toàn văn bản Hợp Đồng Mới (KHÔNG được tóm tắt, phải viết đủ từ đầu đến cuối).
3. Đảm bảo form Markdown chuẩn mực y chang hợp đồng mẫu.
4. CHỈ xuất nội dung Hợp đồng, KHÔNG chào hỏi, KHÔNG giải thích thêm."""


# --- Cấu trúc State của Đồ thị ---
class ReasoningState(TypedDict):
    user_id: str
    session_id: int
    user_input: str

    current_draft: str          # Lưu bản nháp hiện tại của Hợp đồng
    critic_feedback: str        # Lưu lời chê/nhận xét của Trưởng Phòng
    is_passed: bool             # Cờ đánh giá của Trưởng Phòng
    revision_count: int         # Đếm số vòng lặp đã qua

    path_name: str              # Tên file xuất ra cuối cùng
    status: str                 # error / success
    mess: str                   # Lỗi nếu có


# =============================================================================
# CÁC NODE (TÁC TỬ)
# =============================================================================

async def drafter_node(state: ReasoningState):
    """Tác tử: Luật sư tập sự soạn bản nháp (Draft V1) dựa trên User Input."""
    logger.info("[Reasoning] DRAFTER bắt đầu soạn nháp...")

    user_req = state["user_input"]

    from service.runtime_config_service import (
        get_required_active_prompt_content,
        resolve_model_runtime,
        PROMPT_FEATURE_CONTRACT_REASONING_DRAFTER,
    )

    model_selector = state.get("model_name")
    client, resolved_model, meta = await resolve_model_runtime(model_selector)
    current_prompt = await get_required_active_prompt_content(
        PROMPT_FEATURE_CONTRACT_REASONING_DRAFTER
    )

    try:
        response = await client.chat.completions.create(
            model=resolved_model,
            messages=[
                {"role": "system", "content": current_prompt},
                {"role": "user", "content": f"Yêu cầu tạo hợp đồng: {user_req}"},
            ],
            temperature=0.7,
            max_tokens=8000,
        )
        draft = response.choices[0].message.content
        logger.info(
            "[Reasoning][Drafter] Provider=%s Model=%s",
            meta.get("provider_name"),
            resolved_model,
        )
        return {"current_draft": draft, "revision_count": 0, "status": "ok"}
    except Exception as e:
        logger.error(f"[Drafter] Error: {e}")
        return {"status": "error", "mess": str(e)}


async def critic_node(state: ReasoningState):
    """Tác tử: Trưởng phòng vào đọc nháp và chấm điểm Pass/Fail JSON."""
    logger.info(f"[Reasoning] CRITIC đang soi lỗi (Revision {state.get('revision_count', 0)})...")

    draft = state["current_draft"]
    user_req = state["user_input"]

    prompt = (
        f"YÊU CẦU CỦA KHÁCH HÀNG: {user_req}\n\n"
        f"BẢN NHÁP HIỆN TẠI ĐỂ BẠN REVIEW:\n{draft}\n\n"
        f"Hãy trả về JSON theo đúng định dạng."
    )

    from service.runtime_config_service import (
        get_required_active_prompt_content,
        resolve_model_runtime,
        PROMPT_FEATURE_CONTRACT_REASONING_CRITIC,
    )

    model_selector = state.get("model_name")
    client, resolved_model, meta = await resolve_model_runtime(model_selector)
    current_prompt = await get_required_active_prompt_content(
        PROMPT_FEATURE_CONTRACT_REASONING_CRITIC
    )

    try:
        response = await client.chat.completions.create(
            model=resolved_model,
            messages=[
                {"role": "system", "content": current_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,  # Nhiệt độ thấp cho Critic để nó logic & khắt khe
            max_tokens=2000,
            extra_body={"guided_json": {
                "type": "object",
                "properties": {
                    "pass": {"type": "boolean"},
                    "feedback": {"type": "string"}
                },
                "required": ["pass", "feedback"]
            }}
        )

        result_text = response.choices[0].message.content
        logger.debug(f"[Critic JSON]: {result_text}")

        try:
            # Xóa codeblock markdown nếu có sinh nhầm
            clean_text = result_text.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(clean_text)
            is_passed = parsed.get("pass", False)
            feedback = parsed.get("feedback", "Không có nhận xét")
        except Exception:
            # Fallback nếu parse JSON lỗi
            is_passed = False
            feedback = result_text

        logger.info(
            "[Reasoning][Critic] Provider=%s Model=%s Pass=%s",
            meta.get("provider_name"),
            resolved_model,
            is_passed,
        )
        return {"is_passed": is_passed, "critic_feedback": feedback}
    except Exception as e:
        logger.error(f"[Critic] Error: {e}")
        return {"status": "error", "mess": str(e)}


async def reviser_node(state: ReasoningState):
    """Tác tử: Luật sư Senior sửa bản nháp dựa trên Feedback của sếp Critic."""
    revision = state.get("revision_count", 0) + 1
    logger.info(f"[Reasoning] REVISER đang nỗ lực sửa lỗi (Revision {revision})...")

    draft = state["current_draft"]
    feedback = state["critic_feedback"]

    prompt = (
        f"BẢN NHÁP CŨ BỊ LỖI:\n{draft}\n\n"
        f"PHÊ BÌNH CỦA TRƯỞNG PHÒNG (Sửa theo lệnh này):\n{feedback}\n\n"
        f"Hãy xuất lại toàn bộ nội dung hợp đồng MỚI sau khi đã sửa."
    )

    from service.runtime_config_service import (
        get_required_active_prompt_content,
        resolve_model_runtime,
        PROMPT_FEATURE_CONTRACT_REASONING_REVISER,
    )

    model_selector = state.get("model_name")
    client, resolved_model, meta = await resolve_model_runtime(model_selector)
    current_prompt = await get_required_active_prompt_content(
        PROMPT_FEATURE_CONTRACT_REASONING_REVISER
    )

    try:
        response = await client.chat.completions.create(
            model=resolved_model,
            messages=[
                {"role": "system", "content": current_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=8000,
        )
        new_draft = response.choices[0].message.content
        logger.info(
            "[Reasoning][Reviser] Provider=%s Model=%s Revision=%d",
            meta.get("provider_name"),
            resolved_model,
            revision,
        )
        return {
            "current_draft": new_draft,
            "revision_count": revision
        }
    except Exception as e:
        logger.error(f"[Reviser] Error: {e}")
        return {"status": "error", "mess": str(e)}


async def generate_word_node(state: ReasoningState):
    """Sinh file docx từ bản nháp tốt nhất (sau khi pass hoặc hết số lần lặp)."""
    logger.info("[Reasoning] Bắt đầu sinh file Word cuối cùng...")

    if state.get("status") == "error":
        return state

    final_text = state["current_draft"]

    # Đặt tên file logic
    title_match = "reasoning_contract"
    import re
    m = re.search(r"##\s+(.+)", final_text)
    if m:
        clean_title = re.sub(r'[^a-zA-Z0-9_\u00E0-\u1EF9]', '_', m.group(1).strip())
        title_match = clean_title[:40].strip('_')

    import uuid
    uid = uuid.uuid4().hex[:6]
    contract_name = f"{title_match}_{uid}"

    try:
        from agent_chatbot.node.util.contract_create_util import save_response_to_word

        result = save_response_to_word(final_text, contract_name)

        if result.get("status") == "ok":
            logger.info(f"[Reasoning] Đã lưu file Docx: {result.get('path_name')}")
            return {
                "path_name": result.get("path_name"),
                "status": "ok"
            }
        else:
            return {"status": "error", "mess": "Lỗi khi lưu Docx"}
    except Exception as e:
        logger.error(f"[Reasoning WordGen] Lỗi: {e}")
        return {"status": "error", "mess": f"Lỗi tạo file Word: {e}"}


# =============================================================================
# CONDITION EDGE (HÀM ĐIỀU HƯỚNG ROUTER LANGGRAPH)
# =============================================================================

def should_continue_router(state: ReasoningState):
    """
    Quyết định chuyển từ Critic sang Reviser hay kết thúc (Word Gen).
    """
    if state.get("status") == "error":
        return "end"  # Nếu có lỗi phần cứng thì sập luôn đồ thị

    is_passed = state.get("is_passed", False)
    rev_count = state.get("revision_count", 0)

    if is_passed:
        logger.info("[Router] Trưởng phòng PASS -> Gen file.")
        return "generate_word_node"

    if rev_count >= MAX_REVISIONS:
        logger.warning(f"[Router] Draft FAILED nhưng đã lặp mệt mỏi {MAX_REVISIONS} lần -> Ép kết thúc ra file!")
        return "generate_word_node"

    logger.info("[Router] Trưởng phòng FAIL -> Trả về mắng Reviser.")
    return "reviser_node"
