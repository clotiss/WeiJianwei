"""Isolated UI acceptance fixture: synthetic content, no model requests or live DB writes."""
import os
import tempfile
from pathlib import Path

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='weijianwei-summary-ui-') as root:
        os.environ['POLICY_DATABASE_URL']='sqlite:///'+str(Path(root)/'ui.db')
        os.environ['POLICY_AI_KEY']='fixture-only-never-used'
        os.environ.pop('POLICY_AI_CONFIG_FILE',None)
        from policy_v2.app import app, SessionLocal
        from policy_v2.models import Document, Revision, Task, SummaryRecord, now
        from policy_v2.summaries import summary_input
        states=['ready','queued','generating','retrying','failed','waiting_content','insufficient_content']
        quote='这是隔离测试使用的原文引句，仅供验证摘要展示与引用展开功能。'
        with SessionLocal.begin() as db:
            for i,state in enumerate(states,1):
                doc=Document(source_id='nhc-policy',url=f'https://example.invalid/ui-only/{i}',region='CN',status='ready')
                db.add(doc);db.flush()
                rev=Revision(document_id=doc.id,number=1,fingerprint=str(i),title='摘要展示验收样例 · '+state,
                    body=quote*5,kind='policy',published='2026-11-17',summary_status=state,
                    summary=[{'text':'此样例用于验证摘要及原文依据展示。','quote':quote,'source':'body','source_name':'正文','location':{},'start':0,'end':len(quote)}] if state=='ready' else [])
                db.add(rev);db.flush();doc.current_revision=rev.id
                task=Task(kind='summary',key='ui:'+str(i),payload={'revision_id':rev.id},state={'ready':'succeeded','generating':'running','failed':'failed'}.get(state,'queued'),attempts=1 if state in ('retrying','failed') else 0,available=now()+60)
                db.add(task);db.flush()
                content,_=summary_input(rev)
                db.add(SummaryRecord(revision_id=rev.id,task_id=task.id,input_sha=content['sha'],model='fixture',prompt_version='fixture',scope='body',input_chars=len(rev.body),generated=now() if state=='ready' else None))
        import uvicorn
        uvicorn.run(app,host='127.0.0.1',port=8893)
