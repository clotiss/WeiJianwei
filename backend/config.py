import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'nhc_policy.db')}"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

SCRAPER_INTERVAL_HOURS = int(os.getenv("SCRAPER_INTERVAL_HOURS", "6"))
SCRAPER_TARGET_URL = "http://www.nhc.gov.cn/wjw/gfxwj/list.shtml"

SUMMARY_MAX_TOKENS = 500
