import time
import pytest
from policy_v2.db import Base, database
from policy_v2.models import CollectionRun, Source
from policy_v2.rounds import config_hash
from policy_v2.trial import prepare, report


def test_trial_uses_its_own_database_and_does_not_extend_deadline(tmp_path):
    root=tmp_path/'trial'
    _,metadata,settings,engine,factory=prepare(root,['gd-policy','nx-policy'],3)
    try:
        with factory() as db:
            assert {s.id for s in db.query(Source) if s.enabled}=={'gd-policy','nx-policy'}
        assert settings.database_url=='sqlite:///'+str(root/'trial.db')
        assert settings.object_root==root/'objects'
    finally:engine.dispose()
    _,second,_,engine,_=prepare(root,['nx-policy','gd-policy'],3)
    engine.dispose()
    assert second['deadline']==metadata['deadline']
    with pytest.raises(ValueError,match='trial_configuration_mismatch'):
        prepare(root,['gd-policy'],3)
    other=tmp_path/'existing';other.mkdir();(other/'production.db').write_bytes(b'keep')
    with pytest.raises(ValueError,match='trial_root_must_be_empty'):
        prepare(other,['gd-policy'],3)
    assert (other/'production.db').read_bytes()==b'keep'


@pytest.mark.parametrize('scenario',['healthy','one_smoke_run','long_gap','late_completion','pending_task'])
def test_multi_day_verdict_requires_actual_spaced_completed_runs(tmp_path,scenario):
    engine,factory=database('sqlite:///'+str(tmp_path/'test.db'))
    Base.metadata.create_all(engine)
    start=time.time()-3*86400
    metadata={'started':start,'deadline':start+3*86400,'days':3,'sources':['test']}
    with factory.begin() as db:
        source=Source(id='test',name='Test',region='CN',kind='policy',url='https://official.gov.cn/',
                      enabled=True,interval_seconds=21600,config={})
        db.add(source);db.flush()
        count=1 if scenario=='one_smoke_run' else 12
        for i in range(count):
            finished=start+3600+i*21600
            if scenario=='long_gap':finished=start+3600+i*60
            if scenario=='late_completion':finished=metadata['deadline']+3600+i
            db.add(CollectionRun(source_id='test',bucket=i,config_hash=config_hash(source),
                state='running' if scenario=='pending_task' and i==11 else 'succeeded',
                started=start+i*21600,finished=finished,listing_complete=True))
    try:
        assert report(factory,metadata,now=start+7200)['verdict']=='observing'
        final=report(factory,metadata,now=metadata['deadline']+1)
        assert final['verdict']==('passed' if scenario=='healthy' else 'needs_attention')
    finally:engine.dispose()
