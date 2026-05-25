"""使用 DeepSeek API 提取政策文件的关键内容要点。"""

import json
import httpx
from config import DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_BASE_URL, SUMMARY_MAX_TOKENS

SYSTEM_PROMPT = """你是一个医疗政策文件分析助手。请从以下政策文件正文中提取 3-5 个关键要点。

要求：
- 每条要点 1-2 句话，直接说明政策要求或变化
- 按重要性排序
- 输出为 JSON 数组格式：["要点一内容", "要点二内容", ...]
- 只输出 JSON，不要其他文字"""


async def extract_key_points(content: str) -> list[str]:
    """调用 DeepSeek API 提取关键内容。返回要点字符串列表。"""
    if not DEEPSEEK_API_KEY:
        return []

    # 截断过长内容
    text = content[:8000]

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": DEEPSEEK_MODEL,
                    "max_tokens": SUMMARY_MAX_TOKENS,
                    "temperature": 0.3,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": text},
                    ],
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                raw = data["choices"][0]["message"]["content"]
                return json.loads(raw.strip())
        except Exception:
            pass
    return []
