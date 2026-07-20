"""
Module xây dựng 2 workflow LangGraph cho Contract pipeline.

Workflow 1 - upload_template_workflow:
    parse_docling_node → save_template_node → END

Workflow 2 - create_contract_workflow:
    ask_llm_node → (error? END) → create_word_node → END
"""

from langgraph.graph import StateGraph, END
from agent_chatbot.agent_state.agent_state import UploadTemplateState, ContractState
from agent_chatbot.node.contract_upload_pipeline import (
    parse_docling_node,
    save_template_node,
)
from agent_chatbot.node.contract_create_pipeline import (
    ask_llm_node,
    create_word_node,
)
from agent_chatbot.node.contract_fast_pipeline import (
    ask_llm_fast_node,
    create_word_node as create_word_fast_node,
)
from agent_chatbot.node.contract_reasoning_pipeline import (
    drafter_node,
    critic_node,
    reviser_node,
    generate_word_node,
    should_continue_router,
    ReasoningState
)


# =============================================================================
# WORKFLOW 1: Upload Template
# =============================================================================

upload_graph = StateGraph(UploadTemplateState)

upload_graph.add_node("parse_docling_node", parse_docling_node)
upload_graph.add_node("save_template_node", save_template_node)

upload_graph.set_entry_point("parse_docling_node")

upload_graph.add_conditional_edges(
    "parse_docling_node",
    lambda state: "end" if state.get("status") == "error" else "save",
    {
        "end": END,
        "save": "save_template_node",
    }
)

upload_graph.add_edge("save_template_node", END)

upload_template_workflow = upload_graph.compile()


# =============================================================================
# WORKFLOW 2: Create Contract
# =============================================================================

contract_graph = StateGraph(ContractState)

contract_graph.add_node("ask_llm_node", ask_llm_node)
contract_graph.add_node("create_word_node", create_word_node)

contract_graph.set_entry_point("ask_llm_node")

contract_graph.add_conditional_edges(
    "ask_llm_node",
    lambda state: "end" if state.get("status") == "error" else "create",
    {
        "end": END,
        "create": "create_word_node",
    }
)

contract_graph.add_edge("create_word_node", END)

create_contract_workflow = contract_graph.compile()


# =============================================================================
# WORKFLOW 3: Create Contract Fast
# =============================================================================

contract_fast_graph = StateGraph(ContractState)

contract_fast_graph.add_node("ask_llm_fast_node", ask_llm_fast_node)
contract_fast_graph.add_node("create_word_fast_node", create_word_fast_node)

contract_fast_graph.set_entry_point("ask_llm_fast_node")

contract_fast_graph.add_conditional_edges(
    "ask_llm_fast_node",
    lambda state: "end" if state.get("status") == "error" else "create",
    {
        "end": END,
        "create": "create_word_fast_node",
    }
)

contract_fast_graph.add_edge("create_word_fast_node", END)

create_contract_fast_workflow = contract_fast_graph.compile()


# =============================================================================
# WORKFLOW 4: Create Contract Reasoning (Multi-Agent Loop)
# =============================================================================

contract_reasoning_graph = StateGraph(ReasoningState)

contract_reasoning_graph.add_node("drafter_node", drafter_node)
contract_reasoning_graph.add_node("critic_node", critic_node)
contract_reasoning_graph.add_node("reviser_node", reviser_node)
contract_reasoning_graph.add_node("generate_word_node", generate_word_node)

contract_reasoning_graph.set_entry_point("drafter_node")

# Drafter làm xong nháp 1 -> gửi cho Critic chấm
contract_reasoning_graph.add_edge("drafter_node", "critic_node")

# Routing từ Critic: PASS thì in file, FAIL thì qua Reviser
contract_reasoning_graph.add_conditional_edges(
    "critic_node",
    should_continue_router,
    {
        "generate_word_node": "generate_word_node",
        "reviser_node": "reviser_node",
        "end": END
    }
)

# Reviser sửa xong -> gửi lại cho Critic chấm
contract_reasoning_graph.add_edge("reviser_node", "critic_node")

# Bước in File là bước cuối cùng
contract_reasoning_graph.add_edge("generate_word_node", END)

create_contract_reasoning_workflow = contract_reasoning_graph.compile()
