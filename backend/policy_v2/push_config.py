"""Validate the real WeChat template before enabling policy notifications."""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

from dotenv import set_key
from .settings import Settings
from .push import WeChatSender

EXPECTED_FIELDS = {'thing5', 'number12', 'date7', 'thing4'}


def validate_template(settings, template_id):
    import re
    sender = WeChatSender(settings)
    try:
        response = sender.client.get('https://api.weixin.qq.com/wxaapi/newtmpl/gettemplate',
                                      params={'access_token': sender.access_token()})
        if response.status_code != 200: raise ValueError('template_service_unavailable')
        payload = response.json()
        if payload.get('errcode', 0): raise ValueError('template_service_rejected')
        template = next((item for item in payload.get('data', []) if item.get('priTmplId') == template_id), None)
        if not template: raise ValueError('template_not_owned_by_app')
        fields = set(re.findall(r'{{(\w+)\.DATA}}', template.get('content', '')))
        if fields != EXPECTED_FIELDS or str(template.get('type')) != '2':
            raise ValueError('template_fields_or_subscription_type_mismatch')
        if template.get('title') != '政策更新通知': raise ValueError('template_scenario_mismatch')
        return template
    finally: sender.close()


def configure(path, template_id, backup):
    if not path.is_file(): raise ValueError('existing_private_configuration_missing')
    settings = Settings(_env_file=path)
    if not settings.wechat_app_id or not settings.wechat_secret:
        raise ValueError('existing_wechat_credentials_missing')
    template = validate_template(settings, template_id)
    backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if backup.exists(): raise ValueError('backup_already_exists')
    shutil.copyfile(path, backup); backup.chmod(0o600)
    descriptor, name = tempfile.mkstemp(prefix='.push-config-', dir=path.parent)
    os.close(descriptor)
    staged = Path(name)
    try:
        staged.write_bytes(path.read_bytes())
        set_key(str(staged), 'POLICY_WECHAT_PUSH_TEMPLATE_ID', template_id)
        set_key(str(staged), 'POLICY_WECHAT_PUSH_ENABLED', 'true')
        check = Settings(_env_file=staged)
        assert check.wechat_push_enabled and check.wechat_push_template_id == template_id
        assert check.wechat_secret == settings.wechat_secret and check.wechat_app_id == settings.wechat_app_id
        staged.chmod(0o600); os.replace(staged, path)
    finally:
        if staged.exists(): staged.unlink()
    return {'status': 'configured', 'template_title': template['title'], 'mode': 'once', 'send_time': '09:00 Asia/Shanghai'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', type=Path, required=True)
    parser.add_argument('--template', required=True)
    parser.add_argument('--backup', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(configure(args.env, args.template, args.backup), ensure_ascii=False), flush=True)
    except Exception as exc:
        # Never print HTTP request URLs, credential-bearing settings or exception chains.
        safe_codes = {'template_service_unavailable', 'template_service_rejected', 'template_not_owned_by_app',
            'template_fields_or_subscription_type_mismatch', 'template_scenario_mismatch',
            'existing_private_configuration_missing', 'existing_wechat_credentials_missing', 'backup_already_exists'}
        print(json.dumps({'status':'configuration_failed', 'reason':str(exc) if str(exc) in safe_codes else 'wechat_configuration_check_failed'}), flush=True)
        raise SystemExit(1)


if __name__ == '__main__': main()
