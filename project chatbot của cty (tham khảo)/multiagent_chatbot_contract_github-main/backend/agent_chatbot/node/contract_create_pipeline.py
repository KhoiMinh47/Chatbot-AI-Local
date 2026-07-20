"""Module chứa các node xử lý trong pipeline tạo hợp đồng.

Pipeline gồm 2 node:
    1. ask_llm_node: Gọi vLLM với câu hỏi user + template content.
    2. create_word_node: Lưu response LLM thành file Word.

Không streaming trong pipeline — streaming tóm tắt được thực hiện ở service layer.
"""

import logging

from agent_chatbot.node.util.contract_create_util import (
    ask_llm_with_template,
    save_response_to_word,
)

logger = logging.getLogger(__name__)


async def ask_llm_node(state):
    """
    Node gọi vLLM để tạo nội dung hợp đồng từ template.
    Không streaming — trả toàn bộ text khi xong.
    """
    user_input = state.get("user_input")
    template_content = state.get("template_content")
    model_name = state.get("model_name")

    try:
        llm_response = await ask_llm_with_template(user_input, template_content, model_name)
        logger.info("ask_llm_node: thành công, %d ký tự", len(llm_response))
        return {
            "llm_response": llm_response,
            "mess": llm_response,
            "status": "ok",
        }

    except Exception as e:
        logger.error("ask_llm_node: lỗi - %s", repr(e))
        return {
            "llm_response": "",
            "mess": f"Lỗi khi gọi LLM: {e}",
            "status": "error",
        }


def create_word_node(state):
    """
    Node lưu response LLM thành file Word.
    """
    llm_response = state.get("llm_response")
    contract_name = state.get("contract_name")

    try:
        result = save_response_to_word(llm_response, contract_name)
        logger.info("create_word_node: status=ok, file=%s", result["path_name"])
        return result

    except Exception as e:
        logger.error("create_word_node: lỗi - %s", repr(e))
        return {
            "status": "error",
            "path_name": "",
            "mess": f"Lỗi khi tạo file Word: {e}",
        }
