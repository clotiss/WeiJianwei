"""
===============================================================================
Agent API — 智能检索接口
===============================================================================

本模块暴露一个 POST 接口，接收用户的自然语言查询，返回结构化的检索结果。

与普通搜索（/api/v1/documents/search）的区别：
- 普通搜索：关键词 LIKE 匹配 → 返回文件列表
- Agent 搜索：LLM 理解查询 → 多策略搜索 → LLM 评估 → 生成回答 + 文件列表

接口：
  POST /api/v1/agent/search   — 智能检索（接收 query，返回 answer + documents + thinking_steps）
  GET  /api/v1/agent/health    — 健康检查
"""

from fastapi import APIRouter
from services.agent3 import langchain_agent_service as agent_service
from schemas import AgentRequest, AgentResponse

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


@router.post("/search", response_model=AgentResponse)
def agent_search(request: AgentRequest):
    """
    智能检索 — 用自然语言搜索政策文件。

    支持两种模式：
    - 单轮模式：只传 query，每次独立检索
    - 多轮模式：传 query + session_id，自动结合对话历史理解指代词和追问

    请求示例（单轮）：
        POST /api/v1/agent/search
        {"query": "最近关于医院感染控制的规范性文件有哪些"}

    请求示例（多轮）：
        POST /api/v1/agent/search
        {"query": "第一个文件的具体内容是什么", "session_id": "user-abc-123"}
    """
    if request.session_id:
        result = agent_service.chat(request.query, session_id=request.session_id)
    else:
        result = agent_service.search(request.query)

    # thinking_steps 里的 emoji 在 JSON 里没问题，
    # documents 已经是 dict 列表，直接返回即可
    return AgentResponse(
        answer=result["answer"],
        documents=result["documents"],
        thinking_steps=result["thinking_steps"],
    )


@router.get("/health")
def agent_health():
    """Agent 服务健康检查 — 确认 DeepSeek API Key 是否已配置。"""
    from config import DEEPSEEK_MODEL
    if agent_service.api_key:
        return {
            "status": "ok",
            "model": DEEPSEEK_MODEL,
            "message": "Agent 服务正常运行",
        }
    return {
        "status": "degraded",
        "model": DEEPSEEK_MODEL,
        "message": "DEEPSEEK_API_KEY 未配置，Agent 将降级为简单关键词搜索",
    }
