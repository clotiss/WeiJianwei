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
    session_days: int = 30
    recruitment_enabled: bool = False

TOPICS = ['中医药与民族医药','医疗服务与质量安全','医疗机构与执业人员管理','卫生信息化与标准','卫生监督与行政执法','妇幼健康与人口发展','疾病预防控制与公共卫生','综合与健康促进']
REGIONS = {'CN':'国家','JS':'江苏','HN':'湖南','GD':'广东'}
