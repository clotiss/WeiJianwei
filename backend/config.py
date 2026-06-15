"""
===============================================================================
应用配置 — 集中管理所有可配置参数
===============================================================================

包含数据库连接、AI 模型、爬虫调度等核心配置项。
支持通过环境变量覆盖默认值，方便在不同环境（开发/生产）中部署。

配置项说明：
- DATABASE_URL: SQLite 数据库文件路径
- DEEPSEEK_*: DeepSeek AI 大模型的 API 配置
- SCRAPER_*: NHC 官网爬虫的调度参数
- SUMMARY_MAX_TOKENS: AI 摘要生成的最大 token 数
"""

import os

# ---------- 路径配置 ----------
# 获取当前文件所在目录的绝对路径（backend/）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------- 数据库配置 ----------
# SQLite 数据库文件路径：backend/nhc_policy.db
# SQLite 是一个轻量级文件型数据库，无需额外安装服务
DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'nhc_policy.db')}"

# ---------- DeepSeek AI 配置 ----------
# API Key：从环境变量获取，若不设置则 AI 摘要功能不可用但不会报错
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
# 使用的模型名称，deepseek-v4-pro 是最新版本
DEEPSEEK_MODEL = "deepseek-v4-pro"
# API 基础地址
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# ---------- 爬虫调度配置 ----------
# 定时抓取间隔（小时），默认每 6 小时抓取一次
# 可通过环境变量 SCRAPER_INTERVAL_HOURS 覆盖
SCRAPER_INTERVAL_HOURS = int(os.getenv("SCRAPER_INTERVAL_HOURS", "6"))
# NHC 卫健委规范性文件列表页 URL
SCRAPER_TARGET_URL = "http://www.nhc.gov.cn/wjw/gfxwj/list.shtml"

# ---------- AI 摘要配置 ----------
# 单次调用 DeepSeek 的最大输出 token 数（约 800 个中文字符）
SUMMARY_MAX_TOKENS = 800
