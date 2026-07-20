"""
Module chứa các node xử lý trong pipeline upload template hợp đồng.

Pipeline gồm 2 node:
    1. parse_docling_node: Gọi Docling API parse file sang markdown.
    2. save_template_node: Lưu file local và upload MinIO.

Các node gọi tới các hàm tiện ích trong contract_upload_util.py.
"""

import logging

from agent_chatbot.node.util.contract_upload_util import (
    parse_template_docling,
    save_template_file,
)

logger = logging.getLogger(__name__)


# =============================================================================
# CÁC NODE TRONG PIPELINE
# =============================================================================


async def parse_docling_node(state):
    """
    Node gọi Docling API để parse file template sang markdown.

    Input:
        state: Chứa filename, file_content.

    Output:
        dict: Cập nhật parsed_content, status, mess.
    """

    filename = state.get("filename")
    file_content = state.get("file_content")

    try:
        parsed_content = await parse_template_docling(filename, file_content)

        logger.info("parse_docling_node: thành công, %d ký tự", len(parsed_content))

        return {
            "parsed_content": parsed_content,
            "status": "ok",
        }

    except Exception as e:
        logger.error("parse_docling_node: lỗi - %s", repr(e))

        return {
            "parsed_content": "",
            "status": "error",
            "mess": f"Lỗi khi parse template bằng Docling: {e}",
        }


def save_template_node(state):
    """
    Node lưu file template xuống local và upload MinIO.

    Input:
        state: Chứa filename, file_content.

    Output:
        dict: Cập nhật file_path, minio_path, status, mess.
    """

    filename = state.get("filename")
    file_content = state.get("file_content")

    try:
        result = save_template_file(filename, file_content)

        logger.info("save_template_node: status=ok")

        return {
            "file_path": result["file_path"],
            "minio_path": result["minio_path"],
            "status": "ok",
        }

    except Exception as e:
        logger.error("save_template_node: lỗi - %s", repr(e))

        return {
            "file_path": "",
            "minio_path": "",
            "status": "error",
            "mess": f"Lỗi khi lưu file template: {e}",
        }
