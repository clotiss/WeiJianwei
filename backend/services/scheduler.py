"""定时调度：抓取 NHC → 去重入库 → AI 摘要。"""

import re
import json
import asyncio
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

from database import SessionLocal
from models import Document
from services.scraper import fetch_document_list, fetch_document_detail
from services.summary import extract_key_points
from config import SCRAPER_INTERVAL_HOURS

# 分类关键词映射
CATEGORY_KEYWORDS = {
    "医政管理": ["医疗机构", "医院", "医疗质量", "医疗服务", "医政", "医师", "护士", "感染防控", "医疗安全"],
    "疾控": ["疾控", "传染病", "疫苗接种", "疫情防控", "公共卫生", "疾病预防"],
    "妇幼健康": ["妇幼", "母婴", "儿童", "妇产", "出生缺陷", "两癌"],
    "基层卫生": ["基层", "社区卫生", "乡镇卫生", "村卫生", "家庭医生", "基本公卫"],
    "药政": ["药品", "药物", "基本药物", "处方", "药事", "抗菌药物", "麻精"],
    "医管": ["医保", "DRG", "DIP", "支付", "绩效考核", "评审", "医管"],
}


def classify_document(title: str) -> tuple[str, str]:
    """根据标题关键词分类，返回 (category, doc_type)。"""
    category = "其他"
    for cat_name, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in title:
                category = cat_name
                break
        if category != "其他":
            break

    # 二级分类
    if "通知" in title or "印发" in title or "发布" in title:
        doc_type = "通知公告"
    elif "解读" in title or "一图读懂" in title:
        doc_type = "政策解读"
    elif "办法" in title or "规范" in title or "标准" in title or "指南" in title:
        doc_type = "规范性文件"
    else:
        doc_type = "规范性文件"

    return category, doc_type


def extract_doc_number(title: str) -> str:
    """从标题中提取文号（如有）。"""
    m = re.search(r"[〔（【]\d{4}[〕）】]\d+号", title)
    return m.group(0) if m else ""


async def run_scrape_pipeline():
    """执行一次完整抓取流水线。"""
    print(f"[{datetime.now()}] Starting scrape pipeline...")
    items = await fetch_document_list()
    print(f"  Fetched {len(items)} items from NHC")

    db = SessionLocal()
    try:
        for item in items:
            # 去重（按 URL）
            existing = db.query(Document).filter(Document.original_url == item["url"]).first()
            if existing:
                continue

            # 抓详情
            detail = await fetch_document_detail(item["url"])
            content = detail.get("content", "")

            # AI 摘要
            summary_points = await extract_key_points(content)
            summary = json.dumps(summary_points, ensure_ascii=False) if summary_points else ""

            # 分类
            category, doc_type = classify_document(item["title"])
            doc_number = extract_doc_number(item["title"])

            doc = Document(
                title=item["title"],
                doc_number=doc_number,
                issuing_authority="国家卫生健康委",
                publish_date=item["publish_date"],
                category=category,
                doc_type=doc_type,
                original_url=item["url"],
                summary=summary,
                attachments=json.dumps(detail.get("attachments", []), ensure_ascii=False),
            )
            db.add(doc)
            print(f"  + {item['title'][:50]}...")
        db.commit()
    finally:
        db.close()
    print(f"[{datetime.now()}] Pipeline done.")


def start_scheduler():
    """启动后台定时调度器。"""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        lambda: asyncio.run(run_scrape_pipeline()),
        "interval",
        hours=SCRAPER_INTERVAL_HOURS,
        id="nhc_scraper",
    )
    scheduler.start()
    print(f"Scheduler started, interval={SCRAPER_INTERVAL_HOURS}h")
    return scheduler
