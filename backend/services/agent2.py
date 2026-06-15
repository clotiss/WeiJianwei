import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_BASE_URL
import httpx
from services.summary import CATEGORY_LIST,CATEGORIES_PROMPT
import json

# =============================================================================
# 会话历史存储（内存版，重启丢失，学习阶段够用）
# =============================================================================
_sessions: dict[str, list[dict]] = {}  # {session_id: [{role, content}, ...]}

def _load_history(session_id: str, max_messages: int = 6) -> list[dict]:
    """加载最近 N 条历史消息（滑动窗口，防爆 context window）。"""
    messages = _sessions.get(session_id, [])
    return messages[-max_messages:] if len(messages) > max_messages else messages

def _save_message(session_id: str, role: str, content: str):
    """保存一条消息。注意：只存 query 和 answer，不存文件正文。"""
    if session_id not in _sessions:
        _sessions[session_id] = []
    _sessions[session_id].append({"role": role, "content": content})

def _format_history(messages: list[dict]) -> str:
    """把消息列表转为可嵌入 prompt 的文本。"""
    if not messages:
        return "（无历史对话）"
    lines = []
    for msg in messages:
        if msg["role"] == "user":
            lines.append(f"用户：{msg['content']}")
        else:
            lines.append(f"助手：{msg['content'][:150]}")
    return "\n".join(lines)

SYSTEM_PROMPT = f"""你是一个医疗政策文件分析助手。请根据用户的查询文本完成以下任务：
1. 从以下 8 个分类中选择最匹配的一个（只能从这 8 个中选，不要自创或使用其他分类名）：{CATEGORIES_PROMPT}
2.对用户query进行意图分析，提取出用户查询的关键词，返回一个关键词列表。
3.意图改写：将用户的查询改写为一个更适合用于数据库搜索的查询语句，要求保留原意但更简洁明了。
4.严格按照以下格式返回结果：
{{
  "category": "分类名称",
  "time":"要查找的时间",
  "keywords": ["关键词1", "关键词2", ...],
  "rewritten_query": "改写后的查询语句"
}}"""

# 多轮版 prompt — 注入对话历史，让 LLM 理解指代词和追问
SYSTEM_PROMPT_WITH_HISTORY = f"""你是一个医疗政策文件分析助手。请根据对话历史和用户当前查询完成以下任务。

## 对话历史：
{{history}}

## 用户当前问题：
{{query}}

注意：
- 如果用户说"第一个""上面提到的""上一篇"等指代词，根据历史推断具体指什么
- 如果用户的问题是追问，保持和历史主题一致

请完成：
1. 从以下 8 个分类中选择最匹配的一个（只能从这 8 个中选）：{CATEGORIES_PROMPT}
2. 提取关键词列表
3. 将查询改写为适合数据库搜索的语句（结合历史上下文）
4. 严格输出 JSON：
{{{{"category": "分类名", "time": "时间范围", "keywords": ["k1","k2"], "rewritten_query": "改写后"}}}}
"""   


def understand_query(content: str, session_id: str = None)->tuple[str, list[str],str, str]:
    """
    调用 DeepSeek API 理解用户查询意图。
    如果传入 session_id 且存在历史对话，会将历史注入 prompt 以理解指代词和追问。

    参数：
        content: 用户输入的查询文本
        session_id: 可选，会话标识

    返回：(category, keywords, rewritten_query, time)
    """

    if not DEEPSEEK_API_KEY:
        print("DeepSeek API key not configured. Returning empty response.")
        return "", [],"",""

    # ---- 选择 prompt：有历史用多轮版，无历史用单轮版 ----
    if session_id:
        history = _load_history(session_id)
        if history:
            prompt = SYSTEM_PROMPT_WITH_HISTORY.format(
                history=_format_history(history), query=content
            )
        else:
            prompt = SYSTEM_PROMPT
    else:
        prompt = SYSTEM_PROMPT

    with httpx.Client() as client:
        try:
            response = client.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                         "Content-Type": "application/json"},
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": [{"role": "system", "content": prompt},
                                 {"role":"user","content": content}],
                    "max_tokens": 500,
                    "temperature": 0.3
                }
            )
            if response.status_code == 200:
                data=response.json()
                print(data)
                raw_content=data["choices"][0]["message"]["content"]
                presed=json.loads(raw_content)
                category=presed.get("category","")
                keywords=presed.get("keywords",[])
                rewritten_query=presed.get("rewritten_query","")
                time=presed.get("time","")
                if category not in CATEGORY_LIST:
                    print(f"Warning: AI returned invalid category '{category}'. Defaulting to empty string.")
                    category=""
                return category, keywords, rewritten_query,time

        except Exception as e:
            print(f"Error occurred: {e}")

    return "", [], "",""


def search(query: str, session_id: str = None) -> dict:
    """完整的检索流程。当前只有查询理解，后续步骤待实现。"""
    category, keywords, rewritten_query, time = understand_query(query, session_id)

    # 保存本轮对话
    if session_id:
        _save_message(session_id, "user", query)
        # TODO: 等 step_search/evaluate/synthesize 完成后保存助手回答
        # _save_message(session_id, "assistant", answer)

    return {
        "category": category,
        "keywords": keywords,
        "rewritten_query": rewritten_query,
        "time": time,
    }


if __name__ == "__main__":
    query = "我想找一下关于儿童疫苗的政策文件，最好是最近两年发布的。"
    category, keywords, rewritten_query,time =  understand_query(query)
    print(f"Category: {category}")
    print(f"Keywords: {keywords}")
    print(f"Rewritten Query: {rewritten_query}")
    print(f"Time: {time}")
