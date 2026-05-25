"""NHC 规范性文件列表页抓取。使用 Playwright 无头浏览器（Firefox）绕过 JS 反爬和 WAF。"""

import asyncio
import re
from datetime import datetime
from playwright.async_api import async_playwright


NHC_LIST_URL = "https://www.nhc.gov.cn/wjw/gfxwj/list.shtml"
BASE_URL = "https://www.nhc.gov.cn"


async def fetch_document_list() -> list[dict]:
    """抓取 NHC 规范性文件列表页，返回文件元信息列表。"""
    results = []
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page()
        await page.goto(NHC_LIST_URL, wait_until="networkidle", timeout=30000)

        # 等待列表渲染
        await page.wait_for_selector(".zxxx_list li", timeout=10000)

        items = await page.query_selector_all(".zxxx_list li")
        for item in items:
            try:
                link_el = await item.query_selector("a")
                if not link_el:
                    continue
                title = (await link_el.inner_text()).strip()
                href = await link_el.get_attribute("href")

                # 拼接完整 URL
                if href and not href.startswith("http"):
                    href = BASE_URL + href if href.startswith("/") else f"{BASE_URL}/{href}"

                # 提取日期（span.ml 是 NHC 列表页的日期样式）
                date_el = await item.query_selector("span.ml, span")
                date_str = ""
                if date_el:
                    date_str = (await date_el.inner_text()).strip()
                    date_str = re.sub(r"[\[\]]", "", date_str)

                results.append({
                    "title": title,
                    "url": href or "",
                    "publish_date": date_str or datetime.now().strftime("%Y-%m-%d"),
                })
            except Exception:
                continue

        await browser.close()
    return results


async def fetch_document_detail(url: str) -> dict:
    """抓取单篇文件详情页，返回正文内容和附件信息。"""
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)

        content = ""
        attachments = []

        try:
            content_el = await page.query_selector(".con, #content, .TRS_Editor, .article-con")
            if content_el:
                content = (await content_el.inner_text()).strip()
        except Exception:
            content = ""

        # 提取附件
        try:
            attach_els = await page.query_selector_all(
                "a[href$='.pdf'], a[href$='.doc'], a[href$='.docx'], "
                "a[href$='.xls'], a[href$='.xlsx']"
            )
            for a in attach_els:
                name = (await a.inner_text()).strip()
                href = await a.get_attribute("href")
                if name and href:
                    attachments.append({"name": name, "url": href})
        except Exception:
            pass

        await browser.close()
    return {"content": content, "attachments": attachments}
