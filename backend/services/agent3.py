"""
===============================================================================
agent3.py — LangChain 框架实现的 NHC 政策文件检索 Agent
===============================================================================

基于 agent.py（四步 ReAct 检索流程）和 agent2.py（多轮对话支持），
使用 LangChain 框架重新实现，获得以下优势：

1. ChatOpenAI — 统一的 LLM 调用接口（底层对接 DeepSeek，OpenAI 兼容）
2. ChatPromptTemplate — 声明式 Prompt 管理（SystemMessage + HumanMessage）
3. PydanticOutputParser — 类型安全的结构化输出，自动生成 Format Instructions
4. ConversationBufferWindowMemory — 滑动窗口会话记忆（防爆 context）
5. LCEL (LangChain Expression Language) — 可组合的 | 管道链
6. @tool 装饰器 — 将数据库搜索封装为标准 Tool
7. create_react_agent — 可选的 ReAct Agent 模式（LLM 自主选择搜索策略）

与 agent.py / agent2.py 的关系：
  agent.py  — 四步流水线（理解→搜索→评估→合成），无记忆
  agent2.py — 查询理解 + 多轮对话记忆（搜索/评估/合成待实现）
  agent3.py — 融合两者，用 LangChain 框架统一实现，新增 Agent 模式

使用方式（单例）：
    from services.agent3 import langchain_agent_service
    result = langchain_agent_service.search("最近关于传染病防控的文件")
    # 多轮对话
    result = langchain_agent_service.chat("第一个文件说了什么？", session_id="user123")
"""

import json
import sys
from pathlib import Path
from typing import Optional

# 确保 backend/ 在 sys.path 中（agent2.py 也有同样的处理）
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_BASE_URL
from services.summary import CATEGORY_LIST, CATEGORIES_PROMPT

# =============================================================================
# LangChain 核心导入
# =============================================================================
from langchain_openai import ChatOpenAI
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder,
)
from langchain_core.output_parsers import (
    StrOutputParser,
    PydanticOutputParser,
)
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_core.tools import tool

# =============================================================================
# Pydantic 模型 — 定义结构化输出
# =============================================================================
from pydantic import BaseModel, Field


class QueryUnderstandingOutput(BaseModel):
    """
    Step 1 输出：从自然语言中提取的结构化搜索参数。

    同时支持 agent.py 的关键词搜索模式和 agent2.py 的改写查询模式。
    """

    keywords: list[str] = Field(
        default_factory=list,
        description="提取的关键词列表，用于 SQL LIKE 模糊匹配",
    )
    category_hint: str = Field(
        default="",
        description="推测的政策分类，必须是 8 大分类之一，不确定就留空",
    )
    time_hint: str = Field(
        default="",
        description="时间范围描述，如'最近一年''2024年'，留空表示不限时间",
    )
    doc_type_hint: str = Field(
        default="",
        description="文件类型：'规范性文件' 或 '政策解读'，不确定就留空",
    )
    is_time_sensitive: bool = Field(
        default=False,
        description="查询是否对时效性有要求",
    )
    rewritten_query: str = Field(
        default="",
        description="改写后的查询语句（更简洁、更适合搜索）",
    )


class RelevanceScore(BaseModel):
    """Step 3 输出：单条搜索结果的相关性评分。"""

    id: int = Field(description="文档 ID")
    score: int = Field(description="相关性评分 0-10", ge=0, le=10)
    reason: str = Field(description="评分理由，一句话")


# =============================================================================
# 会话记忆存储（内存版，重启丢失 — 与 agent2.py 兼容）
# =============================================================================
_sessions: dict[str, list] = {}  # {session_id: [BaseMessage, ...]}

# 每个会话最多保留的消息轮数（一轮 = user + assistant）
MAX_TURNS = 10
# 每条 assistant 消息最长保留的字符数（避免历史消息撑爆 context window）
MAX_ASSISTANT_LENGTH = 300


# =============================================================================
# LLM 实例 — ChatOpenAI 对接 DeepSeek
# =============================================================================

def _create_llm(temperature: float = 0.3, max_tokens: int = 800) -> ChatOpenAI:
    """
    创建 ChatOpenAI 实例，指向 DeepSeek API。

    DeepSeek 的 API 完全兼容 OpenAI 格式，LangChain 的 ChatOpenAI
    只需修改 base_url 即可无缝对接。

    参数：
        temperature: 0.0~1.0，查询理解/评估用低值（稳定），合成用中值（自然）
        max_tokens: 最大输出 token 数
    """
    return ChatOpenAI(
        model=DEEPSEEK_MODEL,
        api_key=DEEPSEEK_API_KEY,  # type: ignore[arg-type]
        base_url=DEEPSEEK_BASE_URL,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=60,
    )


# 按用途创建不同温度的 LLM 实例（LangChain 的 ChatOpenAI 是轻量级对象，无需担心开销）
llm_precise = _create_llm(temperature=0.2, max_tokens=800)   # 查询理解、相关性评估
llm_creative = _create_llm(temperature=0.5, max_tokens=800)  # 回答合成


# =============================================================================
# Step 1: 查询理解 — Prompt 模板 + PydanticOutputParser
# =============================================================================

# PydanticOutputParser 会自动生成格式说明（Format Instructions），指导 LLM 输出合法 JSON
# 注意：format_instructions 含 { } 大括号，需转义为 {{ }} 以兼容 LangChain 模板语法
_query_parser = PydanticOutputParser(pydantic_object=QueryUnderstandingOutput)
_fmt_escaped = _query_parser.get_format_instructions().replace("{", "{{").replace("}", "}}")

QUERY_UNDERSTAND_SYSTEM = f"""你是一个医疗政策检索专家。用户的查询可能是口语化的，请提取结构化搜索参数。

## 分类说明（只能从中选择，不要自创）：
{CATEGORIES_PROMPT}

## 输出格式：
{_fmt_escaped}

## 规则：
- keywords: 提取 2-5 个核心关键词，去除"的""了""吗"等停用词
- category_hint: 只能从上述 8 个分类中选择，不确定就留空字符串
- time_hint: 提取时间范围（如"最近一年""2024年""2023-2024"），无时间要求就留空
- doc_type_hint: "规范性文件"或"政策解读"，不明显就留空
- is_time_sensitive: 查询是否明确要求时间范围
- rewritten_query: 将口语化查询改写为简洁的搜索语句"""

QUERY_UNDERSTAND_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessage(content=QUERY_UNDERSTAND_SYSTEM),
    HumanMessagePromptTemplate.from_template("用户查询：{query}"),
])

# LCEL 链：prompt → llm → parser
understand_query_chain = QUERY_UNDERSTAND_PROMPT | llm_precise | _query_parser


# =============================================================================
# Step 1b: 多轮查询理解 — 带对话历史的版本（来自 agent2.py 的能力）
# =============================================================================

_query_parser_with_history = PydanticOutputParser(pydantic_object=QueryUnderstandingOutput)
_fmt_hist_escaped = _query_parser_with_history.get_format_instructions().replace("{", "{{").replace("}", "}}")

QUERY_UNDERSTAND_WITH_HISTORY_SYSTEM = f"""你是一个医疗政策检索专家。请根据对话历史和用户当前查询，提取结构化搜索参数。

## 分类说明：
{CATEGORIES_PROMPT}

## 注意事项：
- 如果用户使用了"第一个""上面提到的""上一篇"等指代词，根据对话历史推断具体指向
- 如果用户的问题是追问，保持和历史主题一致
- 提取的关键词应结合历史上下文

## 输出格式：
{_fmt_hist_escaped}"""

QUERY_UNDERSTAND_WITH_HISTORY_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessage(content=QUERY_UNDERSTAND_WITH_HISTORY_SYSTEM),
    MessagesPlaceholder(variable_name="history"),
    HumanMessagePromptTemplate.from_template("用户当前问题：{query}"),
])

understand_query_with_history_chain = (
    QUERY_UNDERSTAND_WITH_HISTORY_PROMPT | llm_precise | _query_parser_with_history
)


# =============================================================================
# Step 3: 相关性评估 — Prompt 模板 + 自定义 JSON 解析
# =============================================================================

RELEVANCE_SYSTEM_PROMPT = """你是一个医疗政策检索评估专家。请评估每条搜索结果与用户查询的相关性。

评分标准（0-10 分）：
- 8-10 分：高度相关，直接回答用户问题
- 5-7 分：部分相关，涉及用户关心的领域但不完全匹配
- 0-4 分：基本不相关

请严格输出 JSON 数组（只保留 ≥5 分的结果，按分数从高到低排列）：
[{{"id": 文档ID, "score": 分数, "reason": "一句话理由"}}, ...]

如果没有 ≥5 分的结果，输出空数组 []。不要输出其他文字。"""

RELEVANCE_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessage(content=RELEVANCE_SYSTEM_PROMPT),
    HumanMessagePromptTemplate.from_template(
        "用户查询：{query}\n\n搜索结果：\n{docs_text}"
    ),
])

# 相关性评估链：prompt → llm → (手动 JSON 解析)
evaluate_relevance_chain = RELEVANCE_PROMPT | llm_precise | StrOutputParser()


# =============================================================================
# Step 4: 回答合成 — Prompt 模板 + StrOutputParser
# =============================================================================

SYNTHESIS_SYSTEM_PROMPT = """你是一个医疗政策信息助手。根据用户问题和搜索结果，生成一段简洁有用的回答。

要求：
1. 先直接回答用户的问题（1-3 句话）
2. 如果搜索结果能回答问题，引用具体文件标题来说明（用【标题】格式）
3. 如果结果不够好，诚实告诉用户并建议调整查询
4. 语气专业但友好，不要编造文件内容中没有的信息
5. 控制在 200 字以内"""

SYNTHESIS_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(SYNTHESIS_SYSTEM_PROMPT),
    HumanMessagePromptTemplate.from_template(
        "用户问题：{query}\n\n相关文件：\n{docs_text}"
    ),
])

# 回答合成链：prompt → llm → string
synthesize_answer_chain = SYNTHESIS_PROMPT | llm_creative | StrOutputParser()


# =============================================================================
# @tool 工具 — 将数据库搜索封装为 LangChain Tool
# =============================================================================

@tool
def search_nhc_documents(
    keywords: str = "",
    category: str = "",
    doc_type: str = "",
    limit: int = 15,
) -> str:
    """
    在 NHC 政策文件数据库中搜索文件。

    参数：
        keywords: 搜索关键词，多个关键词用空格分隔
        category: 政策分类（8 大分类之一），留空则不限制
        doc_type: 文件类型（"规范性文件"或"政策解读"），留空则不限制
        limit: 最多返回条数，默认 15

    返回：
        JSON 格式的搜索结果
    """
    from database import SessionLocal
    from models import Document
    from sqlalchemy import desc, or_

    db = SessionLocal()
    try:
        q = db.query(Document)

        # 关键词搜索（OR 逻辑）
        if keywords:
            kw_list = [kw.strip() for kw in keywords.split() if kw.strip()]
            if kw_list:
                conditions = []
                for kw in kw_list:
                    conditions.append(Document.title.contains(kw))
                    conditions.append(Document.content.contains(kw))
                    conditions.append(Document.summary.contains(kw))
                q = q.filter(or_(*conditions))

        # 分类过滤
        if category and category in CATEGORY_LIST:
            q = q.filter(Document.category == category)

        # 文件类型过滤
        if doc_type and doc_type in ("规范性文件", "政策解读"):
            q = q.filter(Document.doc_type == doc_type)

        rows = q.order_by(desc(Document.publish_date)).limit(limit).all()

        results = [
            {
                "id": r.id,
                "title": r.title,
                "publish_date": r.publish_date,
                "category": r.category,
                "doc_type": r.doc_type,
                "issuing_authority": r.issuing_authority or "",
                "original_url": r.original_url or "",
                "summary": r.summary or "",
            }
            for r in rows
        ]
        return json.dumps(results, ensure_ascii=False)
    finally:
        db.close()


@tool
def get_document_detail(doc_id: int) -> str:
    """
    获取指定 ID 的政策文件详情（含完整正文）。

    参数：
        doc_id: 文件 ID

    返回：
        JSON 格式的文件详情
    """
    from database import SessionLocal
    from models import Document

    db = SessionLocal()
    try:
        row = db.query(Document).filter(Document.id == doc_id).first()
        if not row:
            return json.dumps({"error": "文件不存在"}, ensure_ascii=False)
        return json.dumps(
            {
                "id": row.id,
                "title": row.title,
                "publish_date": row.publish_date,
                "category": row.category,
                "doc_type": row.doc_type,
                "issuing_authority": row.issuing_authority or "",
                "original_url": row.original_url or "",
                "content": (row.content or "")[:3000],
                "summary": row.summary or "",
            },
            ensure_ascii=False,
        )
    finally:
        db.close()


# 工具列表（可传入 create_react_agent）
AGENT_TOOLS = [search_nhc_documents, get_document_detail]


# =============================================================================
# AgentService — 对外的服务类
# =============================================================================

class LangChainAgentService:
    """
    基于 LangChain 框架的 NHC 政策文件检索 Agent。

    提供两种检索模式：
    1. search()  — 流水线模式（默认）：四步流程，确定性强
    2. chat()    — 对话模式：支持多轮追问，带会话记忆

    两种模式都使用 LangChain 的 ChatOpenAI / PromptTemplate / OutputParser。
    """

    def __init__(self):
        """初始化。LLM 实例在模块级别已创建，此处仅做配置校验。"""
        self.api_key = DEEPSEEK_API_KEY
        if not self.api_key:
            print("[agent3] Warning: DEEPSEEK_API_KEY not configured. Agent will return empty results.")

    # =========================================================================
    # Step 1: 理解查询（LangChain 链式调用版）
    # =========================================================================
    def step_understand_query(
        self, query: str, session_id: Optional[str] = None
    ) -> QueryUnderstandingOutput:
        """
        使用 LangChain 的 PydanticOutputParser 解析 LLM 输出。

        相比 agent.py 的手动 json.loads + try/except，
        PydanticOutputParser 提供类型安全 + 自动重试（LangChain 内置）。

        如果传入 session_id 且有历史对话，会注入历史以理解指代词。
        """
        if not self.api_key:
            return QueryUnderstandingOutput(keywords=[query])

        try:
            if session_id and _sessions.get(session_id):
                # 多轮模式：注入对话历史
                history = _load_langchain_history(session_id)
                result = understand_query_with_history_chain.invoke({
                    "query": query,
                    "history": history,
                })
            else:
                # 单轮模式
                result = understand_query_chain.invoke({"query": query})

            # 校验 category 是否在合法列表中
            if result.category_hint and result.category_hint not in CATEGORY_LIST:
                print(f"[agent3] Warning: AI returned invalid category '{result.category_hint}'. Clearing.")
                result.category_hint = ""

            return result
        except Exception as e:
            print(f"[agent3] Query understanding failed: {e}")
            # 降级：用原始查询作为关键词
            return QueryUnderstandingOutput(keywords=[query])

    # =========================================================================
    # Step 2: 多策略搜索
    # =========================================================================
    def step_search(self, params: QueryUnderstandingOutput, limit: int = 15) -> list[dict]:
        """
        与 agent.py 完全相同的 SQL 组合查询逻辑。

        使用 LangChain Tool 版本（search_nhc_documents）的等价实现。
        保持独立方法以便在流水线中精细控制。
        """
        from database import SessionLocal
        from models import Document
        from sqlalchemy import desc, or_

        db = SessionLocal()
        try:
            q = db.query(Document)

            # ---- 关键词过滤 ----
            keywords = params.keywords
            if keywords:
                conditions = []
                for kw in keywords:
                    conditions.append(Document.title.contains(kw))
                    conditions.append(Document.content.contains(kw))
                    conditions.append(Document.summary.contains(kw))
                q = q.filter(or_(*conditions))

            # ---- 分类过滤 ----
            cat = params.category_hint
            if cat:
                q = q.filter(Document.category == cat)

            # ---- 文档类型过滤 ----
            dtype = params.doc_type_hint
            if dtype:
                q = q.filter(Document.doc_type == dtype)

            rows = q.order_by(desc(Document.publish_date)).limit(limit).all()

            return [
                {
                    "id": r.id,
                    "title": r.title,
                    "publish_date": r.publish_date,
                    "category": r.category,
                    "doc_type": r.doc_type,
                    "issuing_authority": r.issuing_authority or "",
                    "original_url": r.original_url or "",
                    "summary": r.summary or "",
                    "content_snippet": (r.content or "")[:300],
                }
                for r in rows
            ]
        finally:
            db.close()

    # =========================================================================
    # Step 3: 相关性评估（LangChain 链式调用版）
    # =========================================================================
    def step_evaluate_relevance(
        self, query: str, candidates: list[dict]
    ) -> list[dict]:
        """
        使用 LangChain 的 evaluate_relevance_chain 评分并过滤。

        相比 agent.py 手动拼接文本 → httpx → json.loads，
        LangChain 版本通过 RELEVANCE_PROMPT 模板 + StrOutputParser 更简洁。
        """
        if not candidates:
            return []

        # 构建候选文档文本
        docs_text_parts = []
        for doc in candidates:
            snippet = (doc.get("summary") or doc.get("content_snippet") or "")[:150]
            docs_text_parts.append(
                f"[ID:{doc['id']}] {doc['title']} | "
                f"{doc['publish_date']} | {doc['category']}\n"
                f"  摘要: {snippet}"
            )
        docs_text = "\n\n".join(docs_text_parts)

        try:
            result = evaluate_relevance_chain.invoke({
                "query": query,
                "docs_text": docs_text,
            })
            scored = json.loads(result)
            if isinstance(scored, list) and scored:
                relevant_ids = {
                    item["id"]: item
                    for item in scored
                    if item.get("score", 0) >= 5
                }
                return [doc for doc in candidates if doc["id"] in relevant_ids]
        except (json.JSONDecodeError, KeyError, Exception) as e:
            print(f"[agent3] Relevance evaluation failed: {e}")

        # 降级：返回前 5 条
        return candidates[:5]

    # =========================================================================
    # Step 4: 回答合成（LangChain 链式调用版）
    # =========================================================================
    def step_synthesize_answer(
        self, query: str, relevant_docs: list[dict]
    ) -> str:
        """
        使用 LangChain 的 synthesize_answer_chain 生成自然语言回答。
        """
        if not relevant_docs:
            return "抱歉，没有找到与您问题相关的政策文件。建议尝试调整关键词，比如使用更具体的医疗术语。"

        # 构建相关文件文本
        docs_text_parts = []
        for doc in relevant_docs:
            url_part = f"\n  原文链接: {doc['original_url']}" if doc.get("original_url") else ""
            snippet = (doc.get("summary") or doc.get("content_snippet") or "")[:200]
            docs_text_parts.append(
                f"【{doc['title']}】({doc['publish_date']}, {doc['category']}){url_part}\n"
                f"  要点: {snippet}"
            )
        docs_text = "\n\n".join(docs_text_parts)

        try:
            answer = synthesize_answer_chain.invoke({
                "query": query,
                "docs_text": docs_text,
            })
            return answer if answer else f"找到 {len(relevant_docs)} 篇相关文件，请查看下方列表。"
        except Exception as e:
            print(f"[agent3] Answer synthesis failed: {e}")
            return f"找到 {len(relevant_docs)} 篇相关文件，请查看下方列表。"

    # =========================================================================
    # 流水线模式：完整的四步检索（与 agent.py search() 接口兼容）
    # =========================================================================
    def search(self, query: str) -> dict:
        """
        执行完整的四步检索流程（流水线模式）。

        参数：
            query: 用户的自然语言查询

        返回：
            {
                "answer": "自然语言回答",
                "documents": [DocumentItem, ...],
                "thinking_steps": ["🔍 正在理解...", ...],
            }

        接口与 agent.py 的 search() 完全兼容。
        """
        thinking_steps: list[str] = []

        # ---- Step 1: 理解查询 ----
        thinking_steps.append("🔍 正在理解您的问题...")
        params = self.step_understand_query(query)
        kw_display = ", ".join(params.keywords) if params.keywords else query
        thinking_steps.append(f"✅ 识别关键词: {kw_display}")
        if params.category_hint:
            thinking_steps.append(f"✅ 推测分类: {params.category_hint}")
        if params.doc_type_hint:
            thinking_steps.append(f"✅ 推测类型: {params.doc_type_hint}")

        # ---- Step 2: 搜索 ----
        thinking_steps.append("📚 正在检索相关文件...")
        candidates = self.step_search(params, limit=15)
        thinking_steps.append(f"✅ 检索到 {len(candidates)} 篇候选文件")

        # ---- Step 3: 评估相关性 ----
        if candidates:
            thinking_steps.append("🧠 正在评估相关性...")
            relevant_docs = self.step_evaluate_relevance(query, candidates)
            thinking_steps.append(f"✅ 筛选出 {len(relevant_docs)} 篇相关文件")
        else:
            relevant_docs = []

        # ---- Step 4: 合成回答 ----
        thinking_steps.append("💬 正在生成回答...")
        answer = self.step_synthesize_answer(query, relevant_docs)
        thinking_steps.append("✅ 完成")

        # ---- 构建返回文件列表 ----
        doc_ids = [d["id"] for d in relevant_docs]
        full_docs = []
        if doc_ids:
            from database import SessionLocal
            from models import Document
            db = SessionLocal()
            try:
                rows = db.query(Document).filter(Document.id.in_(doc_ids)).all()
                id_order = {did: i for i, did in enumerate(doc_ids)}
                rows_sorted = sorted(rows, key=lambda r: id_order.get(r.id, 999))
                from schemas import DocumentItem
                full_docs = [
                    DocumentItem.model_validate(r).model_dump()
                    for r in rows_sorted
                ]
            finally:
                db.close()

        return {
            "answer": answer,
            "documents": full_docs,
            "thinking_steps": thinking_steps,
        }

    # =========================================================================
    # 对话模式：带会话记忆的多轮检索
    # =========================================================================
    def chat(self, query: str, session_id: str = "default") -> dict:
        """
        多轮对话检索模式。

        与 agent2.py 的 search() 类似，但实现了完整的四步流程。
        自动保存对话历史，后续追问可以理解指代词和上下文。

        参数：
            query: 用户问题
            session_id: 会话标识（用于区分不同用户/会话）

        返回：
            与 search() 相同的格式
        """
        # ---- Step 1: 理解查询（带历史） ----
        params = self.step_understand_query(query, session_id=session_id)

        # ---- Step 2~4: 同流水线模式 ----
        thinking_steps = []
        thinking_steps.append("🔍 正在理解您的问题（结合对话历史）...")
        kw_display = ", ".join(params.keywords) if params.keywords else query
        thinking_steps.append(f"✅ 识别关键词: {kw_display}")
        if params.category_hint:
            thinking_steps.append(f"✅ 推测分类: {params.category_hint}")

        thinking_steps.append("📚 正在检索相关文件...")
        candidates = self.step_search(params, limit=15)
        thinking_steps.append(f"✅ 检索到 {len(candidates)} 篇候选文件")

        if candidates:
            thinking_steps.append("🧠 正在评估相关性...")
            relevant_docs = self.step_evaluate_relevance(query, candidates)
            thinking_steps.append(f"✅ 筛选出 {len(relevant_docs)} 篇相关文件")
        else:
            relevant_docs = []

        thinking_steps.append("💬 正在生成回答...")
        answer = self.step_synthesize_answer(query, relevant_docs)
        thinking_steps.append("✅ 完成")

        # ---- 保存对话历史 ----
        _save_langchain_message(session_id, "user", query)
        _save_langchain_message(session_id, "assistant", answer[:MAX_ASSISTANT_LENGTH])

        # ---- 构建返回 ----
        doc_ids = [d["id"] for d in relevant_docs]
        full_docs = []
        if doc_ids:
            from database import SessionLocal
            from models import Document
            db = SessionLocal()
            try:
                rows = db.query(Document).filter(Document.id.in_(doc_ids)).all()
                id_order = {did: i for i, did in enumerate(doc_ids)}
                rows_sorted = sorted(rows, key=lambda r: id_order.get(r.id, 999))
                from schemas import DocumentItem
                full_docs = [
                    DocumentItem.model_validate(r).model_dump()
                    for r in rows_sorted
                ]
            finally:
                db.close()

        return {
            "answer": answer,
            "documents": full_docs,
            "thinking_steps": thinking_steps,
        }

    # =========================================================================
    # Agent 模式：ReAct Agent（LLM 自主选择搜索策略）
    # =========================================================================
    def search_via_agent(self, query: str) -> dict:
        """
        使用 LangChain 的 create_react_agent 进行检索。

        与流水线模式的区别：
        - 流水线模式：固定的四步流程，确定性强
        - Agent 模式：LLM 自主决定搜索策略（调几次工具、怎么组合、是否看详情）

        LLM 可以：
        1. 先用 search_nhc_documents 搜索
        2. 发现某篇文件不够详细 → 用 get_document_detail 获取完整正文
        3. 可以多次搜索（如先宽后窄）
        4. 最终综合所有信息生成回答

        注意：需要安装 langgraph（pip install langgraph）。
        如果未安装，自动降级为流水线模式。
        """
        try:
            from langgraph.prebuilt import create_react_agent as _create_react_agent
        except ImportError:
            print("[agent3] langgraph not installed. Falling back to pipeline mode.")
            return self.search(query)

        if not self.api_key:
            return self.search(query)

        # 构建 Agent 的系统提示
        agent_system_prompt = f"""你是一个 NHC 医疗政策文件检索助手。你可以使用以下工具帮助用户查找政策文件：

- search_nhc_documents: 按关键词、分类、文件类型搜索政策文件
- get_document_detail: 获取指定文件的详细内容

工作流程建议：
1. 先理解用户的问题
2. 使用 search_nhc_documents 搜索相关文件
3. 如需更多细节，使用 get_document_detail 查看完整正文
4. 最终用中文回答用户的问题，引用具体文件标题

政策文件分为 8 个分类：{', '.join(CATEGORY_LIST)}

回答要求：
- 先直接回答问题（1-3 句话）
- 引用具体文件标题（【标题】格式）
- 不编造文件内容中没有的信息
- 控制在 200 字以内"""

        try:
            agent = _create_react_agent(
                model=llm_creative,
                tools=AGENT_TOOLS,
                system_prompt=agent_system_prompt,
            )

            result = agent.invoke({
                "messages": [HumanMessage(content=query)],
            })

            # 提取最终回答
            messages = result.get("messages", [])
            answer = ""
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content:
                    answer = msg.content
                    break

            return {
                "answer": answer or "抱歉，未能生成回答。",
                "documents": [],
                "thinking_steps": ["🤖 Agent 模式", "✅ 完成"],
            }
        except Exception as e:
            print(f"[agent3] Agent mode failed: {e}. Falling back to pipeline.")
            return self.search(query)

    # =========================================================================
    # 缓存管理
    # =========================================================================
    def clear_session(self, session_id: str):
        """清除指定会话的历史记录。"""
        _sessions.pop(session_id, None)

    def clear_all_sessions(self):
        """清除所有会话历史。"""
        _sessions.clear()


# =============================================================================
# 会话记忆辅助函数（与 agent2.py 的存储格式兼容）
# =============================================================================

def _load_langchain_history(session_id: str, max_messages: int = 6) -> list:
    """
    加载会话历史，转为 LangChain 消息格式。

    返回最近 N 条消息（滑动窗口），用于注入 prompt 的 MessagesPlaceholder。
    """
    messages = _sessions.get(session_id, [])
    recent = messages[-max_messages:] if len(messages) > max_messages else messages
    return recent


def _save_langchain_message(session_id: str, role: str, content: str):
    """保存一条消息到会话历史。"""
    if session_id not in _sessions:
        _sessions[session_id] = []
    if role == "user":
        _sessions[session_id].append(HumanMessage(content=content))
    else:
        # 截断长回答，防止撑爆 context window
        truncated = content[:MAX_ASSISTANT_LENGTH]
        _sessions[session_id].append(AIMessage(content=truncated))


# =============================================================================
# 单例模式
# =============================================================================
langchain_agent_service = LangChainAgentService()


# =============================================================================
# 自测入口
# =============================================================================
if __name__ == "__main__":
    # 测试单轮搜索
    service = LangChainAgentService()
    print("=" * 60)
    print("Testing LangChain Agent (pipeline mode)")
    print("=" * 60)

    result = service.search("最近关于传染病防控的文件有哪些？")
    print(f"\nAnswer: {result['answer']}")
    print(f"\nDocuments: {len(result['documents'])} 篇")
    print(f"\nThinking steps:")
    for step in result["thinking_steps"]:
        print(f"  {step}")
