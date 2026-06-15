"""
===============================================================================
NHC 批量抓取脚本 — 一次性抓取最近 5 年（2021-2026）政策文件
===============================================================================

用法：
    cd backend && python3 bulk_scrape.py

流程：
  1. 逐页抓取列表页，直到遇到 2021 年之前的文件
  2. 对每条新文件：抓详情 → AI 摘要+分类 → 入库
  3. 按 URL 去重，已存在则跳过（支持中断后重跑）
  4. 进度实时显示

预计耗时：视文件数量，可能 10~30 分钟
"""

import json
import sys
import asyncio
import re
from datetime import datetime, timedelta

# Playwright 异步爬虫
from services.scraper import (
    fetch_document_list,
    fetch_document_detail,
    SOURCE_URLS,
    BASE_URL,
    _setup_page,
    _get_total_pages,
    _fetch_one_page,
)
from services.summary import extract_key_points
from database import SessionLocal
from models import Document
from config import DEEPSEEK_API_KEY

# =============================================================================
# 配置
# =============================================================================

# 抓取起点：从此日期开始的都算"最近 5 年"
FIVE_YEARS_AGO = "2021-01-01"

# 每抓完一页停顿的秒数（避免频率过高被封）
PAGE_DELAY = 1.5

# 详情页抓取间歇
DETAIL_DELAY = 0.8


# =============================================================================
# 主流程
# =============================================================================

def _date_in_range(date_str: str) -> bool:
    """检查日期是否在 2021-01-01 及之后。"""
    if not date_str:
        return True  # 无日期的文件仍抓取
    try:
        return date_str >= FIVE_YEARS_AGO
    except Exception:
        return True


def count_existing() -> int:
    """统计数据库中已有的文件数。"""
    db = SessionLocal()
    try:
        return db.query(Document).count()
    finally:
        db.close()


def url_exists(url: str) -> bool:
    """检查 URL 是否已入库。"""
    db = SessionLocal()
    try:
        return db.query(Document).filter(
            Document.original_url == url
        ).first() is not None
    finally:
        db.close()


async def bulk_scrape():
    """
    批量抓取主函数。
    """
    if not DEEPSEEK_API_KEY:
        print("⚠️  WARNING: DEEPSEEK_API_KEY not set. AI summary will be skipped.")

    existing_before = count_existing()
    print(f"📦 现有数据: {existing_before} 条")
    print(f"📅 目标范围: {FIVE_YEARS_AGO} ~ 至今")
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

                # 构建页码 URL
                if pg == 1:
                    pg_url = first_url
                else:
                    base = first_url.rsplit(".", 1)[0]
                    pg_url = f"{base}_{pg}.shtml"

                items = await _fetch_one_page(page, pg_url, doc_type)
                new_count = 0
                out_of_range_count = 0

                for item in items:
                    if _date_in_range(item.get("publish_date", "")):
                        item["doc_type"] = doc_type
                        if not url_exists(item["url"]):
                            all_items.append(item)
                            new_count += 1
                    else:
                        out_of_range_count += 1

                print(f"   第{pg}页: {len(items)} 条 | 新入库 {new_count} | 超期 {out_of_range_count}")

                # 如果整页都是超期文件，停止该来源
                if out_of_range_count > 0 and new_count == 0 and len(items) > 0:
                    # 连续 2 页无新数据才停止（防止单页全是无日期文件）
                    # 简单策略：该页超过一半是超期文件 → 停止
                    if out_of_range_count >= len(items) * 0.5:
                        stopped_by_date = True
                        print(f"   ⏹ 已到达 {FIVE_YEARS_AGO} 之前，停止 {doc_type}")

                await asyncio.sleep(PAGE_DELAY)

        await browser.close()

    print(f"\n{'=' * 60}")
    print(f"📋 列表抓取完成: 共 {len(all_items)} 条新文件待处理")

    if not all_items:
        print("✅ 没有新文件，数据库已是最新状态。")
        return

    # ---- Phase 2: 逐条处理入库 ----
    print(f"\n📥 开始处理详情页 + AI 摘要...")

    total = len(all_items)
    processed = 0
    failed = 0
    skipped_ai = 0

    for i, item in enumerate(all_items):
        try:
            # 再次去重（Phase 1 后可能已由其他进程入库）
            if url_exists(item["url"]):
                processed += 1
                continue

            # 抓详情页
            detail = await fetch_document_detail(item["url"])
            content = detail.get("content", "")

            # AI 摘要 + 分类
            summary = ""
            category = ""
            if content and DEEPSEEK_API_KEY:
                try:
                    points, category = await extract_key_points(content)
                    summary = json.dumps(points, ensure_ascii=False) if points else ""
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
                    attachments=json.dumps(
                        detail.get("attachments", []), ensure_ascii=False
                    ),
                )
                db.add(doc)
                db.commit()
            finally:
                db.close()

            processed += 1
            pct = processed * 100 // total
            print(f"  [{pct}%] ({processed}/{total}) {category or '?'} | {item['title'][:45]}...")

            await asyncio.sleep(DETAIL_DELAY)

        except Exception as e:
            failed += 1
            print(f"  ❌ [{item.get('title', '?')[:30]}]: {e}")

    # ---- 汇总 ----
    after_count = count_existing()
    print(f"\n{'=' * 60}")
    print(f"✅ 批量抓取完成！")
    print(f"   处理: {processed} 条")
    print(f"   失败: {failed} 条")
    print(f"   AI跳过: {skipped_ai} 条")
    print(f"   数据库: {existing_before} → {after_count} (+{after_count - existing_before})")


if __name__ == "__main__":
    asyncio.run(bulk_scrape())
