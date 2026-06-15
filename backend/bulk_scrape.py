"""
===============================================================================
NHC 批量抓取脚本 — 一次性抓取 2011 年至今的政策文件
===============================================================================

用法：
    cd backend && python3 bulk_scrape.py

流程：
  1. 逐页抓取列表页，直到遇到 START_DATE 之前的文件
  2. 对每条新文件：抓详情 → AI 摘要+分类 → 入库
  3. 按 URL 去重，已存在则跳过（支持中断后重跑）
  4. 进度实时显示

注意：使用 asyncio.wait_for 超时机制，单条卡住 >60s 自动跳过
"""

import json
import sys
import asyncio
import re
from datetime import datetime

from services.scraper import SOURCE_URLS, BASE_URL, _setup_page, _get_total_pages, _fetch_one_page
from services.summary import extract_key_points
from database import SessionLocal
from models import Document
from config import DEEPSEEK_API_KEY

# =============================================================================
# 配置
# =============================================================================
START_DATE = "2011-01-01"       # 抓取起点
PAGE_DELAY = 1.5                # 列表页抓取间歇
DETAIL_TIMEOUT = 60             # 单条详情抓取超时（秒）
AI_TIMEOUT = 30                 # 单条 AI 摘要超时（秒）

# =============================================================================
# 辅助函数
# =============================================================================

def _date_in_range(date_str: str) -> bool:
    if not date_str:
        return True
    try:
        return date_str >= START_DATE
    except Exception:
        return True


def count_existing() -> int:
    db = SessionLocal()
    try:
        return db.query(Document).count()
    finally:
        db.close()


def url_exists(url: str) -> bool:
    db = SessionLocal()
    try:
        return db.query(Document).filter(Document.original_url == url).first() is not None
    finally:
        db.close()


# =============================================================================
# 详情页抓取 — 复用浏览器，解决每次启动 Firefox 的开销
# =============================================================================

async def _fetch_detail_with_browser(page, url: str) -> dict:
    """复用已有 page 实例抓取单篇详情，避免重复启动浏览器。"""
    from playwright.async_api import TimeoutError as PlaywrightTimeout
    content = ""
    attachments = []

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(1500)

        for sel in ["#xw_box", "#UCAP-CONTENT", ".TRS_Editor", ".con", "#content", ".article-con", ".text"]:
            el = await page.query_selector(sel)
            if el:
                text = (await el.inner_text()).strip()
                if len(text) > 100:
                    content = text
                    break

        attach_els = await page.query_selector_all(
            "a[href$='.pdf'], a[href$='.doc'], a[href$='.docx'], a[href$='.xls'], a[href$='.xlsx']"
        )
        for a in attach_els:
            name = (await a.inner_text()).strip()
            href = await a.get_attribute("href")
            if name and href:
                if not href.startswith("http"):
                    href = BASE_URL + href if href.startswith("/") else f"{BASE_URL}/{href}"
                attachments.append({"name": name, "url": href})
    except Exception:
        pass

    return {"content": content, "attachments": attachments}


# =============================================================================
# 主流程
# =============================================================================

async def bulk_scrape():
    if not DEEPSEEK_API_KEY:
        print("⚠️  WARNING: DEEPSEEK_API_KEY not set. AI summary will be skipped.")

    existing_before = count_existing()
    print(f"📦 现有数据: {existing_before} 条")
    print(f"📅 目标范围: {START_DATE} ~ 至今")
    print(f"{'=' * 60}")

    # ---- Phase 1: 收集所有文件列表 ----
    all_items = []

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:132.0) Gecko/20100101 Firefox/132.0",
            locale="zh-CN",
        )
        page = await context.new_page()
        await _setup_page(page)

        for doc_type, first_url in SOURCE_URLS.items():
            print(f"\n🔍 [{doc_type}] 开始抓取列表页...")
            total_pages = await _get_total_pages(page, first_url)
            print(f"   总页数: {total_pages}")

            stopped_by_date = False
            for pg in range(1, total_pages + 1):
                if stopped_by_date:
                    break
                if pg == 1:
                    pg_url = first_url
                else:
                    base = first_url.rsplit(".", 1)[0]
                    pg_url = f"{base}_{pg}.shtml"

                items = await _fetch_one_page(page, pg_url, doc_type)
                new_count = sum(
                    1 for item in items
                    if _date_in_range(item.get("publish_date", "")) and not url_exists(item["url"])
                )
                out_count = sum(1 for item in items if not _date_in_range(item.get("publish_date", "")))

                for item in items:
                    item["doc_type"] = doc_type
                all_items.extend(items)

                print(f"   第{pg}页: {len(items)} 条 | 新入库 {new_count} | 超期 {out_count}")

                if out_count >= len(items) * 0.5 and out_count > 0:
                    stopped_by_date = True
                    print(f"   ⏹ 已到达 {START_DATE} 之前，停止 {doc_type}")

                await asyncio.sleep(PAGE_DELAY)

        # Phase 1.5: 去重
        all_items = [item for item in all_items if not url_exists(item["url"])]
        await browser.close()

    print(f"\n{'=' * 60}")
    print(f"📋 列表抓取完成: 共 {len(all_items)} 条新文件待处理")

    if not all_items:
        print("✅ 没有新文件，数据库已是最新状态。")
        return

    # ---- Phase 2: 逐条处理入库（复用浏览器 + 超时机制） ----
    print(f"\n📥 开始处理详情页 + AI 摘要（超时: 详情{DETAIL_TIMEOUT}s, AI{AI_TIMEOUT}s）...")

    total = len(all_items)
    processed = 0
    failed = 0
    skipped_ai = 0

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:132.0) Gecko/20100101 Firefox/132.0",
            locale="zh-CN",
        )
        detail_page = await context.new_page()
        await _setup_page(detail_page)

        for i, item in enumerate(all_items):
            content = ""
            category = ""
            summary = ""

            try:
                # 超时保护：单条详情抓取
                detail = await asyncio.wait_for(
                    _fetch_detail_with_browser(detail_page, item["url"]),
                    timeout=DETAIL_TIMEOUT,
                )
                content = detail.get("content", "")

                # 超时保护：AI 摘要
                if content and DEEPSEEK_API_KEY:
                    try:
                        points, category = await asyncio.wait_for(
                            extract_key_points(content),
                            timeout=AI_TIMEOUT,
                        )
                        summary = json.dumps(points, ensure_ascii=False) if points else ""
                    except asyncio.TimeoutError:
                        print(f"   ⏰ AI 超时 [{item['title'][:40]}]，跳过摘要")
                        skipped_ai += 1
                    except Exception as e:
                        print(f"   ⚠️ AI 失败 [{item['title'][:30]}]: {e}")
                        skipped_ai += 1

                # 入库
                db = SessionLocal()
                try:
                    doc = Document(
                        title=item["title"],
                        issuing_authority="国家卫生健康委",
                        publish_date=item.get("publish_date", ""),
                        category=category or "",
                        doc_type=item.get("doc_type", ""),
                        original_url=item["url"],
                        content=content,
                        summary=summary,
                        attachments=json.dumps(detail.get("attachments", []), ensure_ascii=False),
                    )
                    db.add(doc)
                    db.commit()
                finally:
                    db.close()

                processed += 1

            except asyncio.TimeoutError:
                failed += 1
                print(f"  ⏰ 详情超时 [{item.get('title', '?')[:40]}]，跳过")

            except Exception as e:
                failed += 1
                print(f"  ❌ [{item.get('title', '?')[:30]}]: {e}")

            # 进度（每 10 条打印一次，减少日志量）
            if processed % 10 == 0 or failed > 0:
                pct = processed * 100 // total
                print(f"  [{pct}%] {processed}/{total} (+{failed}跳过) | {category or '?'} | {item['title'][:45]}...")

        await browser.close()

    # ---- 汇总 ----
    after_count = count_existing()
    print(f"\n{'=' * 60}")
    print(f"✅ 批量抓取完成！")
    print(f"   成功: {processed} 条")
    print(f"   失败/超时: {failed} 条")
    print(f"   AI跳过: {skipped_ai} 条")
    print(f"   数据库: {existing_before} → {after_count} (+{after_count - existing_before})")


if __name__ == "__main__":
    asyncio.run(bulk_scrape())
