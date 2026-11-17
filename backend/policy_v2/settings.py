from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='POLICY_', extra='ignore')
    database_url: str = 'sqlite:///.runtime/policy-v2.db'
    object_root: Path = Path('.runtime/objects')
    storage_backend: str = 'local'
    cos_region: str = ''
    cos_bucket: str = ''
    cos_secret_id: str = ''
    cos_secret_key: str = ''
    admin_token: str = ''
    wechat_app_id: str = ''
    wechat_secret: str = ''
    ai_key: str = ''
    ai_url: str = 'https://api.deepseek.com/v1/chat/completions'
    ai_model: str = 'deepseek-chat'
    public_base: str = 'http://127.0.0.1:8891'
    signing_key: str = ''
    max_download_bytes: int = 30 * 1024 * 1024
    fetch_timeout: int = 30
    browser_ready_timeout: int = 15
    domain_delay_seconds: float = 2.0
    source_cooldown_seconds: int = 300
    task_lease_seconds: int = 300
    task_max_attempts: int = 3
    repair_delay_seconds: int = 21600
    repair_max_cycles: int = 3
    max_scan_pages: int = 1000
    history_refresh_seconds: int = 604800
    session_days: int = 30
    recruitment_enabled: bool = False

TOPICS = ['中医药与民族医药','医疗服务与质量安全','医疗机构与执业人员管理','卫生信息化与标准','卫生监督与行政执法','妇幼健康与人口发展','疾病预防控制与公共卫生','综合与健康促进']
# Read the static directory without importing database/source modules.
import json
REGIONS = {'CN': '国家卫健委', **{p['region']: p['name'] for p in json.loads(
    (Path(__file__).with_name('registry') / 'provinces.json').read_text())}}
