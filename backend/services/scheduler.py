"""
===============================================================================
定时调度器 — 自动抓取 NHC 政策文件
===============================================================================

核心流程：
1. 使用 APScheduler（BackgroundScheduler）每隔 N 小时触发一次
2. 首次运行时抓取前 3 页（冷启动全量），后续只抓第 1 页（增量更新）
3. 每条文件按 original_url 去重，避免重复入库
4. 抓取详情页 → AI 摘要+分类 → 写入数据库

技术要点：
- BackgroundScheduler 在独立线程中运行，不阻塞 FastAPI 主线程
- 抓取任务用 asyncio.run() 包裹异步 Playwright 函数
- 每条文件独立 try-except，单条失败不影响其他文件
"""

import json
import asyncio
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

from database import SessionLocal
from models import Document
from services.scraper import fetch_document_list, fetch_document_detail
from services.summary import extract_key_points
from config import SCRAPER_INTERVAL_HOURS


async def run_scrape_pipeline():
    """
    执行一次完整的抓取流水线。

    流程详解：
    ① 判断数据库是否已有数据 → 决定抓取页数
    ② 调用 NHC 列表页爬虫 → 获取文件元信息列表
    ③ 逐条处理：
       a. 按 URL 去重（已存在的跳过）
       b. 抓取详情页正文
       c. 调用 DeepSeek AI 提取关键要点 + 自动分类
       d. 写入数据库
       e. 单条失败不影响整体
    ④ 提交事务
    """
    # ---- 判断冷启动 or 增量更新 ----
    db = SessionLocal()
    try:
        has_data = db.query(Document).first() is not None    # 是否有任何数据？
    finally:
        db.close()

    # 已有数据 → 增量（只抓第 1 页）；无数据 → 冷启动（抓前 3 页）
    num_pages = 1 if has_data else 3
    print(f"[{datetime.now()}] Starting scrape pipeline "
          f"({'incremental' if has_data else 'initial'}, {num_pages} page(s))...")

    # ---- Step 1: 抓取列表页 ----
    items = await fetch_document_list(num_pages=num_pages)
    print(f"  Fetched {len(items)} items from NHC")

    # ---- Step 2-4: 逐条处理入库 ----
    db = SessionLocal()
    try:
        for item in items:
            try:
                # 去重：按 URL 检查是否已入库
                existing = db.query(Document).filter(
                    Document.original_url == item["url"]
                ).first()
                if existing:
                    continue  # 已存在，跳过

                # 抓取详情页正文
                detail = await fetch_document_detail(item["url"])
                content = detail.get("content", "")

                # AI 摘要 + 分类（一次 API 调用同时完成两项任务）
                summary = ""
                category = ""
                if content:
                    try:
                        points, category = await extract_key_points(content)
                        # 将要点列表转为 JSON 字符串存储
                        summary = json.dumps(points, ensure_ascii=False) if points else ""
                    except Exception as e:
                        print(f"    AI failed: {e}")

                # 创建数据库记录
                doc = Document(
                    title=item["title"],
                    issuing_authority="国家卫生健康委",
                    publish_date=item["publish_date"],
                    category=category or "",          # AI 分类结果
                    doc_type=item["doc_type"],         # 规范性文件 or 政策解读
                    original_url=item["url"],
                    content=content,
                    summary=summary,
                    attachments=json.dumps(
                        detail.get("attachments", []), ensure_ascii=False
                    ),
                )
                db.add(doc)
                print(f"  + [{item['doc_type']}][{category or '?'}] {item['title'][:50]}...")

            except Exception as e:
                # 单条失败不影响其他文件
                print(f"  SKIP [{item.get('title', '?')[:40]}]: {e}")
                continue

        # 批量提交（所有文件处理完毕后一次性写入）
        db.commit()
    finally:
        db.close()

    print(f"[{datetime.now()}] Pipeline done.")


def start_scheduler():
    """
    启动后台定时调度器。

    使用 APScheduler 的 BackgroundScheduler：
    - 在后台线程中运行，不阻塞 FastAPI
    - 按 SCRAPER_INTERVAL_HOURS 间隔执行
    - 任务为 lambda 包装，内部用 asyncio.run() 驱动异步爬虫

    返回 scheduler 实例（可用于测试或手动控制）
    """
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        lambda: asyncio.run(run_scrape_pipeline()),  # 将异步函数包装为同步调用
        "interval",                                   # 间隔触发模式
        hours=SCRAPER_INTERVAL_HOURS,                 # 触发间隔
        id="nhc_scraper",                             # 任务 ID（便于管理）
    )
    scheduler.start()
    print(f"Scheduler started, interval={SCRAPER_INTERVAL_HOURS}h")
    return scheduler
