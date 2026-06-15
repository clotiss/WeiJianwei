"""
===============================================================================
检索 Agent — 基于 LLM 的智能政策文件搜索服务
===============================================================================

这是一个 ReAct（Reasoning + Acting）风格的检索代理，不同于传统的关键词搜索，
它使用 LLM 来理解用户的自然语言查询，进行多策略组合搜索，并通过 LLM 评估
搜索结果的相关性，最终生成带引用的自然语言回答。

四步流程（ReAct Loop）：

  Step 1 - Query Understanding（理解查询）
    ├── 输入：用户自然语言查询（如"最近一年关于基层医疗机构的文件有哪些"）
    └── 输出：结构化搜索参数 {keywords, category_hint, time_hint, doc_type_hint}

  Step 2 - Multi-Strategy Search（多策略搜索）
    ├── 输入：结构化搜索参数
    └── 输出：候选文件列表（SQL 组合查询：keyword LIKE + category + doc_type）

  Step 3 - Relevance Evaluation（相关性评估）
    ├── 输入：用户原始查询 + 候选文件列表
    └── 输出：按相关性排序的文件列表（AI 打分 ≥ 5 分的保留）

  Step 4 - Answer Synthesis（回答合成）
    ├── 输入：用户原始查询 + 相关文件列表
    └── 输出：自然语言回答（引用具体文件名，200 字以内）

使用方式（单例模式）：
    from services.agent import agent_service
    result = agent_service.search("最近关于传染病防控的文件")
    # result = {"answer": "...", "documents": [...], "thinking_steps": [...]}
"""

import json
import httpx
from config import DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_BASE_URL

# =============================================================================
# Prompt 模板 — 指导 LLM 在每个步骤中的行为
# =============================================================================

# Step 1: 查询理解 Prompt
QUERY_UNDERSTAND_PROMPT = """你是一个医疗政策检索专家。用户的查询可能是口语化的，请提取结构化搜索参数。

严格输出 JSON 格式，不要其他文字：
{
  "keywords": ["关键词1", "关键词2", ...],
  "category_hint": "分类名或空字符串",
  "time_hint": "时间范围描述或空字符串（如'最近一年''2024年'）",
  "doc_type_hint": "规范性文件 或 政策解读 或 空字符串",
  "is_time_sensitive": true或false
}

分类名只能从以下选择（不确定就留空）：
综合与健康促进、医疗机构与执业人员管理、医疗服务与质量安全、疾病预防控制与公共卫生、妇幼健康与人口发展、中医药与民族医药、卫生监督与行政执法、卫生信息化与标准"""

# Step 3: 相关性评估 Prompt
RELEVANCE_PROMPT = """你是一个医疗政策检索评估专家。用户查询和一批搜索结果如下。

用户查询：{query}

搜索结果：
{docs_text}

请评估每条结果与查询的相关性（0-10分），只保留 ≥5 分的。按分数从高到低排列。

严格输出 JSON 数组，不要其他文字：
[{{"id": 文档ID, "score": 分数, "reason": "一句话理由"}}, ...]"""

# Step 4: 回答合成 Prompt
SYNTHESIS_PROMPT = """你是一个医疗政策信息助手。根据用户问题和搜索结果，生成一段简洁有用的回答。

用户问题：{query}

相关文件：
{docs_text}

要求：
1. 先直接回答用户的问题（1-3 句话）
2. 如果搜索结果能回答问题，引用具体文件标题来说明（用【标题】格式），并附上原文链接
3. 如果结果不够好，诚实告诉用户并建议调整查询
4. 语气专业但友好，不要编造文件内容中没有的信息

输出纯文本（不是 JSON），控制在 200 字以内。"""


class AgentService:
    """
    检索 Agent 服务类。

    封装了 LLM 调用、SQL 查询、结果评估和回答合成的全部逻辑。
    对外只暴露 search() 方法，调用方无需了解内部实现细节。
    """

    def __init__(self):
        """初始化 Agent 服务，从 config 读取 API 配置。"""
        self.api_key = DEEPSEEK_API_KEY
        self.model = DEEPSEEK_MODEL
        self.base_url = DEEPSEEK_BASE_URL

    def _call_llm(
        self, system_prompt: str, user_content: str,
        temperature: float = 0.3, max_tokens: int = 800
    ) -> str:
        """
        调用 DeepSeek API 的通用方法。

        参数：
            system_prompt: 系统提示词（定义 AI 角色和任务）
            user_content: 用户输入内容
            temperature: 随机性参数（0=确定性，1=创造性）
                        查询理解和评估用 0.2（需稳定），回答合成用 0.5（需自然）
            max_tokens: 最大输出 token 数

        返回：
            AI 的文本响应，失败时返回空字符串

        注意：这里使用同步 httpx.Client（不是 AsyncClient），
        因为 Agent 的 search() 方法在线程池中执行（FastAPI 异步路由），
        不阻塞事件循环。
        """
        if not self.api_key:
            return ""

        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content},
                        ],
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"].strip()
        except Exception:
            pass
        return ""

    # =========================================================================
    # Step 1: 理解查询 — LLM 将自然语言转为结构化搜索参数
    # =========================================================================
    def step_understand_query(self, query: str) -> dict:
        """
        让 LLM 理解用户的自然语言查询，提取结构化参数。

        例如输入"最近关于基层医疗的规范性文件"→
        {keywords:["基层医疗"], category_hint:"医疗机构与执业人员管理",
         doc_type_hint:"规范性文件", is_time_sensitive:true}

        解析失败时降级为简单关键词搜索。
        """
        result = self._call_llm(
            QUERY_UNDERSTAND_PROMPT, query,
            temperature=0.2, max_tokens=400    # 低温度确保稳定输出
        )
        try:
            params = json.loads(result)
            return {
                "keywords": params.get("keywords", []),
                "category_hint": params.get("category_hint", ""),
                "time_hint": params.get("time_hint", ""),
                "doc_type_hint": params.get("doc_type_hint", ""),
                "is_time_sensitive": params.get("is_time_sensitive", False),
            }
        except (json.JSONDecodeError, AttributeError):
            # 解析失败降级：用原始查询作为关键词
            return {
                "keywords": [query], "category_hint": "", "time_hint": "",
                "doc_type_hint": "", "is_time_sensitive": False,
            }

    # =========================================================================
    # Step 2: 多策略搜索 — SQL 组合查询
    # =========================================================================
    def step_search(self, params: dict, limit: int = 15) -> list[dict]:
        """
        根据结构化参数执行 SQL 组合查询。

        查询策略：
        1. 关键词 → 对 title、content、summary 三个字段做 LIKE 模糊匹配
        2. 分类 → 精确匹配 category 字段
        3. 文件类型 → 精确匹配 doc_type 字段

        返回最多 limit 条候选文件，按发布日期降序。
        """
        from database import SessionLocal
        from models import Document
        from sqlalchemy import desc, or_

        db = SessionLocal()
        try:
            q = db.query(Document)

            # ---- 关键词过滤 ----
            # 多个关键词之间是 OR 关系（匹配任意一个即可）
            keywords = params.get("keywords", [])
            if keywords:
                conditions = []
                for kw in keywords:
                    conditions.append(Document.title.contains(kw))
                    conditions.append(Document.content.contains(kw))
                    conditions.append(Document.summary.contains(kw))
                q = q.filter(or_(*conditions))

            # ---- 分类过滤 ----
            cat = params.get("category_hint", "")
            if cat:
                q = q.filter(Document.category == cat)

            # ---- 文档类型过滤 ----
            dtype = params.get("doc_type_hint", "")
            if dtype:
                q = q.filter(Document.doc_type == dtype)

            # 按发布日期降序，限制条数
            rows = q.order_by(desc(Document.publish_date)).limit(limit).all()

            # 转为字典列表（方便后续 LLM 处理）
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
                    "content_snippet": (r.content or "")[:300],  # 只取前 300 字
                }
                for r in rows
            ]
        finally:
            db.close()

    # =========================================================================
    # Step 3: 相关性评估 — LLM 打分排序
    # =========================================================================
    def step_evaluate_relevance(
        self, query: str, candidates: list[dict]
    ) -> list[dict]:
        """
        让 LLM 评估每个候选文件与用户查询的相关性。

        评分为 0-10 分，只保留 ≥ 5 分的结果。
        相比纯关键词匹配，LLM 能理解语义相关性（如同义词、上下文关联）。

        LLM 失败时降级为返回前 5 条。
        """
        if not candidates:
            return []

        # 构建候选文档文本（每个文档一行，含标题、日期、分类、摘要）
        docs_text_parts = []
        for i, doc in enumerate(candidates):
            docs_text_parts.append(
                f"[ID:{doc['id']}] {doc['title']} | "
                f"{doc['publish_date']} | {doc['category']}\n"
                f"  摘要: {doc['summary'][:150] if doc['summary'] else doc['content_snippet'][:150]}"
            )
        docs_text = "\n\n".join(docs_text_parts)

        result = self._call_llm(
            RELEVANCE_PROMPT.format(query=query, docs_text=docs_text),
            "",
            temperature=0.2,    # 低温度确保评分稳定
            max_tokens=600,
        )

        try:
            scored = json.loads(result)
            if isinstance(scored, list):
                # 筛选评分 ≥ 5 的文档 ID
                relevant_ids = {
                    item["id"]: item
                    for item in scored
                    if item.get("score", 0) >= 5
                }
                return [doc for doc in candidates if doc["id"] in relevant_ids]
        except (json.JSONDecodeError, AttributeError, KeyError):
            pass

        # 降级方案：返回前 5 条
        return candidates[:5]

    # =========================================================================
    # Step 4: 回答合成 — LLM 生成自然语言回答
    # =========================================================================
    def step_synthesize_answer(
        self, query: str, relevant_docs: list[dict]
    ) -> str:
        """
        让 LLM 根据用户问题和相关文件生成自然语言回答。

        回答要求：
        - 先直接回答问题（1-3 句）
        - 引用具体文件标题（【标题】格式）
        - 不编造文件内容中没有的信息
        - 控制在 200 字以内
        """
        if not relevant_docs:
            return "抱歉，没有找到与您问题相关的政策文件。建议尝试调整关键词，比如使用更具体的医疗术语。"

        # 构建相关文件文本（含原文链接，让 LLM 可以引用）
        docs_text_parts = []
        for doc in relevant_docs:
            url_part = f"\n  原文链接: {doc['original_url']}" if doc.get("original_url") else ""
            docs_text_parts.append(
                f"【{doc['title']}】({doc['publish_date']}, {doc['category']}){url_part}\n"
                f"  要点: {doc['summary'][:200] if doc['summary'] else doc['content_snippet'][:200]}"
            )
        docs_text = "\n\n".join(docs_text_parts)

        answer = self._call_llm(
            SYNTHESIS_PROMPT.format(query=query, docs_text=docs_text),
            "",
            temperature=0.5,     # 中等温度让回答更自然
            max_tokens=500,
        )

        return answer if answer else f"找到 {len(relevant_docs)} 篇相关文件，请查看下方列表。"

    # =========================================================================
    # 对外接口：完整检索流程
    # =========================================================================
    def search(self, query: str) -> dict:
        """
        执行完整的检索 Agent 流程（四步）。

        参数：
            query: 用户的自然语言查询

        返回：
            {
                "answer": "自然语言回答",
                "documents": [DocumentItem, ...],      # 相关文件完整信息
                "thinking_steps": ["🔍 正在理解...", ...]  # 可视化思考过程
            }

        思考步骤（thinking_steps）展示给用户，让用户看到 Agent 的思考过程，
        增加透明度和可信度。
        """
        thinking_steps = []

        # ---- Step 1: 理解查询 ----
        thinking_steps.append("🔍 正在理解您的问题...")
        params = self.step_understand_query(query)
        thinking_steps.append(
            f"✅ 识别关键词: {', '.join(params['keywords']) if params['keywords'] else query}"
        )
        if params["category_hint"]:
            thinking_steps.append(f"✅ 推测分类: {params['category_hint']}")
        if params["doc_type_hint"]:
            thinking_steps.append(f"✅ 推测类型: {params['doc_type_hint']}")

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

        # ---- 构建返回的文件列表 ----
        # 从数据库重新查询完整信息（保证数据完整性，保持相关性排序）
        doc_ids = [d["id"] for d in relevant_docs]
        full_docs = []
        if doc_ids:
            from database import SessionLocal
            from models import Document
            db = SessionLocal()
            try:
                rows = db.query(Document).filter(Document.id.in_(doc_ids)).all()
                # 保持 LLM 评估的相关性排序
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


# =============================================================================
# 单例模式 — 全局唯一的 Agent 服务实例
# 避免重复创建实例，节省内存
# =============================================================================
agent_service = AgentService()
