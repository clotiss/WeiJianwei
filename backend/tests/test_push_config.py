import pytest
from policy_v2 import push_config
from policy_v2.settings import Settings


def test_configuration_preserves_credentials_and_other_settings(tmp_path,monkeypatch):
    path=tmp_path/'ai.env'; backup=tmp_path/'backups/ai.env'
    original='POLICY_WECHAT_APP_ID=existing-app\nPOLICY_WECHAT_SECRET=private-secret\nPOLICY_AI_CONCURRENCY=10\n# preserved comment\n'
    path.write_text(original)
    monkeypatch.setattr(push_config,'validate_template',lambda settings,template:{'title':'政策更新通知'})
    result=push_config.configure(path,'verified-template',backup)
    settings=Settings(_env_file=path)
    assert settings.wechat_push_enabled and settings.wechat_push_template_id=='verified-template'
    assert settings.wechat_secret=='private-secret' and settings.ai_concurrency==10
    assert backup.read_text()==original and '# preserved comment' in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    assert 'private-secret' not in str(result)


def test_failed_live_validation_changes_nothing(tmp_path,monkeypatch):
    path=tmp_path/'ai.env'; backup=tmp_path/'backup'
    original='POLICY_WECHAT_APP_ID=app\nPOLICY_WECHAT_SECRET=secret\n'
    path.write_text(original)
    def reject(*args): raise ValueError('template_not_owned_by_app')
    monkeypatch.setattr(push_config,'validate_template',reject)
    with pytest.raises(ValueError): push_config.configure(path,'wrong',backup)
    assert path.read_text()==original and not backup.exists()
