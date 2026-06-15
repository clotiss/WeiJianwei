"""
===============================================================================
NHC 官网爬虫 — 使用 Playwright 无头浏览器抓取政策文件
===============================================================================

技术选型：为什么用 Playwright（而不是 requests/httpx）？

NHC 卫健委官网有以下反爬机制：
1. WZWS WAF（Web 应用防火墙）— 检查浏览器指纹（User-Agent、Sec-Fetch 头等）
2. JavaScript 动态渲染 — 分页组件 createPageHTML 由 JS 生成
3. 页面结构不统一 — 不同子站的 CSS 选择器不同

Playwright 启动真实 Firefox 浏览器，能完美绕过以上限制。

抓取流程：
1. 打开列表页 → 获取总页数 → 逐页抓取文件列表
2. 打开详情页 → 提取正文内容 → 提取附件列表
3. 两个来源并行抓取："规范性文件" + "政策解读"
"""

import re
from datetime import datetime
from playwright.async_api import async_playwright


# NHC 卫健委官网基础 URL
BASE_URL = "https://www.nhc.gov.cn"

# =============================================================================
# 抓取来源配置
# 每个来源有独立的列表页 URL，doc_type 直接取来源名称
# =============================================================================
SOURCE_URLS = {
    "规范性文件": "https://www.nhc.gov.cn/wjw/gfxwjj/list.shtml",
    "政策解读": "https://www.nhc.gov.cn/wjw/zcjd/list.shtml",
}

# 首次抓取时每个来源抓前 3 页（约 60 条/来源）
SCRAPE_FIRST_PAGES = 3


async def _setup_page(page):
    """
    为浏览器页面设置真实浏览器指纹。

    模拟真实浏览器的 HTTP 请求头，包括：
    - Accept 系列头（声明支持的 MIME 类型）
    - Sec-Fetch 系列头（现代浏览器的安全策略头）
    - 中文语言偏好（zh-CN）

    这些头部能帮助绕过 WZWS WAF 的基础检测。
    """
    await page.set_viewport_size({"width": 1440, "height": 900})
    await page.set_extra_http_headers({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    })


async def _get_total_pages(page, url: str) -> int:
    """
    获取列表总页数。

    策略：
    1. 优先从页面底部的 "共N页" 文本中提取数字
    2. 如果失败，从分页链接中提取最大页码（如 list_5.shtml → 5）
    3. 都失败则返回 1（至少抓一页）

    需要等待 2 秒因为分页组件由 JS 异步渲染（createPageHTML 函数）。
    """
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        # 等待列表项加载完成
        await page.wait_for_selector(".zxxx_list li", timeout=10000)
        # 再等 2 秒让分页 JS 渲染
        await page.wait_for_timeout(2000)
    except Exception:
        return 1

    # 方法1: 从 "共N页" 提取
    total_el = await page.query_selector("#page_div .total_count span")
    if total_el:
        try:
            text = await total_el.inner_text()
            m = re.search(r"(\d+)", text)             # 匹配数字
            if m:
                return int(m.group(1))
        except Exception:
            pass

    # 方法2: 从分页链接提取最大页码（兜底方案）
    page_links = await page.query_selector_all("#page_div .page_index a")
    max_page = 1
    for link in page_links:
        try:
            href = await link.get_attribute("href")
            if href:
                m = re.search(r"list_?(\d+)", href)   # 匹配 list_N.shtml 中的 N
                if m:
                    max_page = max(max_page, int(m.group(1)))
        except Exception:
            pass
    return max_page


async def _fetch_one_page(page, url: str, doc_type: str) -> list[dict]:
    """
    从单个列表页抓取文件列表。

    提取内容：
    - 文件标题（从 <a> 标签的文本）
    - 文件链接（处理相对路径 → 绝对路径）
    - 发布日期（从 <span> 标签，去掉方括号）
    - 文件类型（由调用方传入）

    返回：[{title, url, publish_date, doc_type}, ...]
    """
    results = []
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        await page.wait_for_selector(".zxxx_list li", timeout=10000)
    except Exception:
        return results  # 页面加载失败，返回空列表

    # 获取所有列表项（li 元素）
    items = await page.query_selector_all(".zxxx_list li")
    for item in items:
        try:
            # ---- 提取标题和链接 ----
            link_el = await item.query_selector("a")
            if not link_el:
                continue
            title = (await link_el.inner_text()).strip()
            href = await link_el.get_attribute("href")

            # 处理相对路径：/xxx → https://www.nhc.gov.cn/xxx
            if href and not href.startswith("http"):
                href = BASE_URL + href if href.startswith("/") else f"{BASE_URL}/{href}"

            # ---- 提取日期 ----
            # span.ml 或 span 元素中的日期（去掉方括号 [2024-06-01] → 2024-06-01）
            date_el = await item.query_selector("span.ml, span")
            date_str = ""
            if date_el:
                date_str = (await date_el.inner_text()).strip()
                date_str = re.sub(r"[\[\]]", "", date_str)  # 去掉 [ 和 ]

            results.append({
                "title": title,
                "url": href or "",
                "publish_date": date_str or datetime.now().strftime("%Y-%m-%d"),
                "doc_type": doc_type,
            })
        except Exception:
            continue  # 单条解析失败跳过，继续处理下一条
    return results


async def fetch_document_list(num_pages: int = None) -> list[dict]:
    """
    抓取 NHC 规范性文件 + 政策解读的列表页。

    参数：
        num_pages: 每个来源抓取前几页（None 则使用默认值 3）

    返回：
        所有文件元信息列表（合并两个来源）

    执行流程：
    1. 启动 Firefox 无头浏览器
    2. 依次处理两个来源（规范性文件、政策解读）
    3. 每个来源：获取总页数 → 逐页抓取 → 合并结果
    4. 关闭浏览器
    """
    if num_pages is None:
        num_pages = SCRAPE_FIRST_PAGES

    all_results = []

    # ---- 启动浏览器 ----
    async with async_playwright() as p:
        # 使用 Firefox（对 NHC 网站兼容性最好）
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:132.0) Gecko/20100101 Firefox/132.0",
            locale="zh-CN",   # 中文语言环境
        )
        page = await context.new_page()
        await _setup_page(page)

        # ---- 遍历两个来源 ----
        for doc_type, first_url in SOURCE_URLS.items():
            try:
                # 获取总页数，决定实际抓取页数
                total_pages = await _get_total_pages(page, first_url)
                print(f"  [{doc_type}] total pages: {total_pages}")

                # 计算要抓的页码：[1, 2, 3, ...]
                pages_to_fetch = list(range(1, min(num_pages, total_pages) + 1))
                print(f"  [{doc_type}] fetching pages: {pages_to_fetch}")

                for pg in pages_to_fetch:
                    if pg == 1:
                        pg_url = first_url                               # 第 1 页就是原始 URL
                    else:
                        # 第 N 页的 URL 格式：list.shtml → list_N.shtml
                        base = first_url.rsplit(".", 1)[0]               # 去掉 .shtml 后缀
                        pg_url = f"{base}_{pg}.shtml"                    # 拼接页码

                    items = await _fetch_one_page(page, pg_url, doc_type)
                    all_results.extend(items)
                    print(f"    page {pg}: {len(items)} items")

            except Exception as e:
                print(f"  [{doc_type}] failed: {e}")

        await browser.close()

    return all_results


async def fetch_document_detail(url: str) -> dict:
    """
    抓取单篇文件详情页。

    参数：
        url: 文件详情页 URL

    返回：
        {"content": "正文内容", "attachments": [{"name": "附件名", "url": "..."}]}

    技术细节：
    - 正文提取按优先级尝试多种 CSS 选择器（NHC 各子站结构不统一）
    - 只有文本长度 > 100 才认为提取成功（过滤导航栏等短文本）
    - 附件自动匹配 PDF、DOC、DOCX、XLS、XLSX 格式
    """
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:132.0) Gecko/20100101 Firefox/132.0",
            locale="zh-CN",
        )
        page = await context.new_page()
        await _setup_page(page)

        # 打开详情页
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)  # 等 JS 渲染完成

        content = ""
        attachments = []

        # ---- 提取正文（多选择器降级策略） ----
        # NHC 不同子站使用不同的 CSS 类名，按优先级依次尝试
        try:
            for sel in [
                "#xw_box",          # 新闻盒子（最常见）
                "#UCAP-CONTENT",    # UCAP 系统内容区
                ".TRS_Editor",      # TRS 编辑器内容
                ".con",             # 通用内容容器
                "#content",         # 通用内容区
                ".article-con",     # 文章内容
                ".text",            # 文本区
            ]:
                el = await page.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if len(text) > 100:   # 确实有正文内容（非导航等短文本）
                        content = text
                        break
        except Exception:
            content = ""

        # ---- 提取附件 ----
        # 匹配常见的办公文档格式链接
        try:
            attach_els = await page.query_selector_all(
                "a[href$='.pdf'], a[href$='.doc'], a[href$='.docx'], "
                "a[href$='.xls'], a[href$='.xlsx']"
            )
            for a in attach_els:
                name = (await a.inner_text()).strip()
                href = await a.get_attribute("href")
                if name and href:
                    # 处理相对路径
                    if not href.startswith("http"):
                        href = BASE_URL + href if href.startswith("/") else f"{BASE_URL}/{href}"
                    attachments.append({"name": name, "url": href})
        except Exception:
            pass

        await browser.close()

    return {"content": content, "attachments": attachments}
