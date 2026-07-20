"""Module chứa các node xử lý trong pipeline tạo hợp đồng nhanh (AI Fast).

Pipeline gồm 2 node:
    1. ask_llm_fast_node: Gọi vLLM sinh hợp đồng từ số 0 theo yêu cầu (không template).
    2. create_word_node: Lưu response LLM thành file Word.
"""

import logging
from agent_chatbot.node.util.contract_create_util import (
    ask_llm_fast,
    save_response_to_word,
)

logger = logging.getLogger(__name__)


async def ask_llm_fast_node(state):
    """
    Node gọi vLLM để tạo phác thảo hợp đồng từ yêu cầu người dùng.
    Không streaming — trả toàn bộ text khi xong.
    """
    user_input = state.get("user_input")
    model_name = state.get("model_name")

    try:
        llm_response = await ask_llm_fast(user_input, model_name)
        logger.info("ask_llm_fast_node: thành công, %d ký tự", len(llm_response))
        return {
            "llm_response": llm_response,
            "mess": llm_response,
            "status": "ok",
        }

    except Exception as e:
        logger.error("ask_llm_fast_node: lỗi - %s", repr(e))
        return {
            "llm_response": "",
            "mess": f"Lỗi khi gọi LLM: {e}",
            "status": "error",
        }


def create_word_node(state):
    """
    Node lưu response LLM thành file Word.
    (Sử dụng lại logic node của luồng Templated)
    """
    llm_response = state.get("llm_response")
    contract_name = state.get("contract_name")

    try:
        result = save_response_to_word(llm_response, contract_name)
        logger.info("Fast Pipeline create_word_node: status=ok, file=%s", result["path_name"])
        return result

    except Exception as e:
        logger.error("Fast Pipeline create_word_node: lỗi - %s", repr(e))
        return {
            "status": "error",
            "path_name": "",
            "mess": f"Lỗi khi tạo file Word: {e}",
        }
