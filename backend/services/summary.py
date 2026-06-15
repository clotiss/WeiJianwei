"""
===============================================================================
AI 摘要服务 — 使用 DeepSeek 大模型提取政策文件关键要点并分类
===============================================================================

核心功能：
1. 将长文本政策文件自动归入 8 个医疗政策分类之一
2. 提取 3-5 个关键要点（每条 1-2 句话，按重要性排序）

技术实现：
- 调用 DeepSeek Chat Completions API（兼容 OpenAI 格式）
- 通过精心设计的 System Prompt 约束输出格式
- JSON 响应解析 + 分类名校验，防止 AI 幻觉生成不存在的分类

费用控制：
- 每次调用只发送正文前 8000 字符（约 4000 个中文字）
- max_tokens 限制为 800（约 400 个中文字的输出）
"""

import json
import httpx
from config import DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_BASE_URL, SUMMARY_MAX_TOKENS

# =============================================================================
# 8 大医疗政策分类（与前端标签对应）
# =============================================================================
CATEGORY_LIST = [
    "综合与健康促进",
    "医疗机构与执业人员管理",
    "医疗服务与质量安全",
    "疾病预防控制与公共卫生",
    "妇幼健康与人口发展",
    "中医药与民族医药",
    "卫生监督与行政执法",
    "卫生信息化与标准",
]

# =============================================================================
# 分类提示词 — 帮助 AI 准确选择分类
# 每个分类都有详细的描述和典型文件举例
# =============================================================================
CATEGORIES_PROMPT = (
    "1. 综合与健康促进：基本医疗卫生制度、健康中国战略、健康素养、爱国卫生、控烟、老龄健康、职业健康基础政策。\n"
    "2. 医疗机构与执业人员管理：医院、基层医疗机构、中医诊所、妇幼保健院、急救中心管理；"
    "医师、护士、乡村医生、医学伦理、科研诚信、资格考试与注册。\n"
    "3. 医疗服务与质量安全：医疗质量、医疗技术临床应用、临床路径、病案管理、医疗纠纷、患者安全、血液管理、医院感染控制。\n"
    "4. 疾病预防控制与公共卫生：传染病、慢性病、精神卫生、免疫规划、病原微生物实验室、突发公共卫生事件应急、监测预警。\n"
    "5. 妇幼健康与人口发展：母婴保健、孕产期保健、儿童保健、出生缺陷防治、辅助生殖、计划生育服务、人口监测与家庭发展。\n"
    "6. 中医药与民族医药：中医药服务体系、中医医师、中药管理、中西医结合、民族医、中医传承与创新。\n"
    "7. 卫生监督与行政执法：公共场所卫生、饮用水卫生、学校卫生、职业卫生、放射卫生、食品安全、行政处罚、行政许可、行政复议。\n"
    "8. 卫生信息化与标准：电子病历、健康档案、区域卫生平台、数据标准、信息安全、互联网+医疗健康、大数据与AI应用。"
)

# =============================================================================
# System Prompt — 指导 AI 的输出格式和任务
# =============================================================================
SYSTEM_PROMPT = f"""你是一个医疗政策文件分析助手。请根据文件标题和正文完成两项任务：

1. 从以下 8 个分类中选择最匹配的一个（只能从这 8 个中选，不要自创或使用其他分类名）：
{CATEGORIES_PROMPT}

2. 提取 3-5 个关键要点，每条 1-2 句话，按重要性排序。

严格输出 JSON 格式，不要其他文字：
{{"category": "分类名", "points": ["要点一", "要点二", ...]}}"""


async def extract_key_points(content: str) -> tuple[list[str], str]:
    """
    调用 DeepSeek API 提取关键内容并分类。

    参数：
        content: 政策文件正文

    返回：
        (要点列表, 分类名) — 如果 API 未配置或调用失败，返回 ([], "")

    处理流程：
    1. 截取前 8000 字符（节省 token 成本）
    2. 构造 API 请求（system prompt + user message）
    3. 发送请求 → 解析 JSON 响应
    4. 校验分类名是否在合法列表中（防止 AI 幻觉）
    """
    # API Key 未配置时直接返回空（优雅降级，不报错）
    if not DEEPSEEK_API_KEY:
        return [], ""

    # 截取前 8000 字符（大约 4000 个中文字，足以覆盖大部分政策文件核心内容）
    text = content[:8000]

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            # 调用 DeepSeek Chat Completions API（与 OpenAI 格式兼容）
            resp = await client.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": DEEPSEEK_MODEL,
                    "max_tokens": SUMMARY_MAX_TOKENS,        # 输出长度限制
                    "temperature": 0.3,                       # 较低温度确保输出稳定
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        # user message 包含标题前 100 字 + 完整截取内容
                        {"role": "user", "content": f"标题：{text[:100]}\n\n正文：{text}"},
                    ],
                },
            )

            if resp.status_code == 200:
                data = resp.json()
                # 提取 AI 返回的文本内容
                raw = data["choices"][0]["message"]["content"]
                # 解析 JSON
                parsed = json.loads(raw.strip())
                points = parsed.get("points", [])
                category = parsed.get("category", "")

                # 安全校验：分类名必须在 8 个合法值内
                # 防止 AI 幻觉生成自定义分类名
                if category not in CATEGORY_LIST:
                    category = ""

                return points, category

        except Exception:
            pass  # 任何异常都静默处理，返回空

    return [], ""
