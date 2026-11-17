"""JSON-lines transport to the real FastAPI routes, using an isolated temporary DB.
Only the external WeChat code exchange is stubbed; API authentication and storage are real.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory(prefix='weijianwei-contract-') as root:
    os.environ['POLICY_DATABASE_URL'] = 'sqlite:///' + str(Path(root) / 'test.db')
    os.environ['POLICY_OBJECT_ROOT'] = str(Path(root) / 'objects')
    os.environ['POLICY_WECHAT_APP_ID'] = 'test-app'
    os.environ['POLICY_WECHAT_SECRET'] = 'test-secret'
    from fastapi.testclient import TestClient
    from policy_v2 import app as module
    from policy_v2.models import Document, Revision
    class WeChatResponse:
        def raise_for_status(self): pass
        def json(self): return {'openid':'frontend-contract-user'}
    module.httpx.get = lambda *args, **kwargs: WeChatResponse()
    with module.SessionLocal.begin() as db:
        for region, source, title in [('GD','gd-policy','广东医疗文件'),('CN','nhc-policy','国家医疗文件'),('JS','js-policy','江苏医疗文件')]:
            doc=Document(source_id=source, region=region, url=f'https://official.example/{region}', status='ready')
            db.add(doc); db.flush()
            rev=Revision(document_id=doc.id, number=1, fingerprint=region, title=title,
                kind='policy', topic='医疗服务与质量安全', authority=region+'发布机构', published='2026-11-17',
                doc_number=region+'-1', body='医疗正文：真实接口契约测试', search_text=title+' 医疗正文',
                summary=[{'text':'医疗摘要','quote':'医疗正文'}],
                attachments=[{'name':'附件.pdf','url':'https://official.example/a.pdf','status':'ready'}])
            db.add(rev); db.flush(); doc.current_revision=rev.id
    with TestClient(module.app) as client:
        for line in sys.stdin:
            command=json.loads(line)
            response=client.request(command['method'], command['path'], headers=command.get('header',{}), json=command.get('data'))
            print(json.dumps({'id':command['id'],'statusCode':response.status_code,'data':response.json()}, ensure_ascii=False), flush=True)
    module.engine.dispose()
