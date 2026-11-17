from fastapi.testclient import TestClient

from policy_v2 import app as app_module


def test_read_api_and_admin_auth(monkeypatch):
    monkeypatch.setattr(app_module.settings, "admin_token", "test-admin-secret")
    with TestClient(app_module.app) as client:
        assert client.get("/health").json()["status"] == "ok"
        coverage = client.get("/api/v2/coverage")
        assert coverage.status_code == 200
        assert len(coverage.json()) >= 8
        assert all(not item["enabled"] for item in coverage.json())
        assert client.get("/api/v2/admin/sources").status_code == 401
        result = client.get("/api/v2/admin/sources", headers={"Authorization": "Bearer test-admin-secret"})
        assert result.status_code == 200
        assert len(result.json()) >= 8


def test_unavailable_document_returns_404():
    with TestClient(app_module.app) as client:
        assert client.get("/api/v2/policies/999999").status_code == 404


def test_classification_review_requires_valid_topic_and_audits_change(monkeypatch):
    from policy_v2.models import Audit, Document, Revision, Source
    import uuid
    monkeypatch.setattr(app_module.settings, "admin_token", "review-secret")
    source_id = "nhc-policy"
    with app_module.SessionLocal.begin() as db:
        source = db.get(Source, source_id)
        if not source:
            source = Source(id=source_id, name="National", region="CN", kind="policy",
                url="https://www.nhc.gov.cn/wjw/gfxwjj/list.shtml", config={"hosts": ["www.nhc.gov.cn"]})
            db.add(source)
        document = Document(source_id=source_id, url=f"https://www.nhc.gov.cn/test/{uuid.uuid4().hex}.shtml", region="CN")
        db.add(document); db.flush()
        revision = Revision(document_id=document.id, number=1, fingerprint=uuid.uuid4().hex,
            title="Test policy", body="Test body", kind="policy", classification_status="review")
        db.add(revision); db.flush(); revision_id=revision.id
        document.current_revision=revision_id
    headers={"Authorization":"Bearer review-secret"}
    with TestClient(app_module.app) as client:
        invalid=client.put(f"/api/v2/admin/revisions/{revision_id}/classification", headers=headers,
                           json={"topic":"unknown","reason":"reviewed source material"})
        assert invalid.status_code == 422
        result=client.put(f"/api/v2/admin/revisions/{revision_id}/classification", headers=headers,
                          json={"topic":"医疗服务与质量安全","reason":"body supports this topic"})
        assert result.status_code == 200
        assert result.json()["human_locked"] is True
    with app_module.SessionLocal() as db:
        revision=db.get(Revision,revision_id)
        audit=db.query(Audit).filter_by(target=str(revision_id),action="classification.review").one()
        assert revision.topic == "医疗服务与质量安全" and revision.human_locked
        assert audit.reason == "body supports this topic"


def test_public_policy_list_and_detail_return_only_current_published_revision():
    from policy_v2.models import Document, Revision, Source
    import uuid
    unique_title=f"Health policy test {uuid.uuid4().hex}"
    source_id = "nhc-policy"
    with app_module.SessionLocal.begin() as db:
        source = db.get(Source, source_id)
        if not source:
            source = Source(id=source_id, name="National", region="CN", kind="policy",
                url="https://www.nhc.gov.cn/wjw/gfxwjj/list.shtml", config={"hosts": ["www.nhc.gov.cn"]})
            db.add(source)
        doc = Document(source_id=source_id, url=f"https://www.nhc.gov.cn/test/{uuid.uuid4().hex}.shtml", region="CN", status="ready")
        db.add(doc); db.flush()
        rev = Revision(document_id=doc.id, number=1, fingerprint=uuid.uuid4().hex,
            title=unique_title, body="Policy body", authority="National Health Commission",
            published="2026-11-01", doc_number="NHC-TEST-1", kind="policy",
            topic="医疗服务与质量安全", classification_status="review", summary=[{"text":"Key point","quote":"Policy body"}],
            attachments=[])
        db.add(rev); db.flush(); doc.current_revision=rev.id
        doc_id=doc.id
    with TestClient(app_module.app) as client:
        listing=client.get("/api/v2/policies",params={"q":unique_title,"content_type":"policy"})
        assert listing.status_code == 200 and listing.json()["total"] == 1
        item=listing.json()["items"][0]
        assert item["id"] == doc_id and item["region"] == "CN"
        detail=client.get(f"/api/v2/policies/{doc_id}")
        assert detail.status_code == 200
        assert detail.json()["document_number"] == "NHC-TEST-1"
        assert detail.json()["body"] == "Policy body"


def test_wechat_login_favorite_and_follow_are_account_scoped(monkeypatch):
    from policy_v2.models import Document, Revision, Source, Favorite, Follow
    import uuid
    monkeypatch.setattr(app_module.settings, "wechat_app_id", "test-app")
    monkeypatch.setattr(app_module.settings, "wechat_secret", "test-secret")
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"openid":"test-openid-unique"}
    monkeypatch.setattr(app_module.httpx, "get", lambda *args, **kwargs: Response())
    with app_module.SessionLocal.begin() as db:
        source=db.get(Source,"nhc-policy")
        if not source:
            source=Source(id="nhc-policy",name="National",region="CN",kind="policy",
                url="https://www.nhc.gov.cn/wjw/gfxwjj/list.shtml",config={"hosts":["www.nhc.gov.cn"]})
            db.add(source)
        doc=Document(source_id="nhc-policy",url=f"https://www.nhc.gov.cn/test/{uuid.uuid4().hex}.shtml",region="CN",status="ready")
        db.add(doc);db.flush()
        rev=Revision(document_id=doc.id,number=1,fingerprint=uuid.uuid4().hex,title="Favorite test",body="body",kind="policy")
        db.add(rev);db.flush();doc.current_revision=rev.id;doc_id=doc.id
    with TestClient(app_module.app) as client:
        login=client.post("/api/v2/auth/wechat",json={"code":"mock-code"})
        assert login.status_code==200
        headers={"Authorization":"Bearer "+login.json()["access_token"]}
        assert client.put(f"/api/v2/me/favorites/{doc_id}",headers=headers).json()["favorited"]
        assert client.get("/api/v2/me/favorites",headers=headers).json()[0]["id"]==doc_id
        follow=client.post("/api/v2/me/follows",headers=headers,json={"region":"CN","topic":"","include_national":True})
        assert follow.status_code==200
        assert len(client.get("/api/v2/me/follows",headers=headers).json())==1
        assert client.delete(f"/api/v2/me/favorites/{doc_id}",headers=headers).json()["favorited"] is False
        assert client.get("/api/v2/me/favorites",headers=headers).json()==[]
        assert client.get("/api/v2/me/favorites").status_code==401


def test_national_inventory_distinguishes_registration_from_enabled_coverage():
    with TestClient(app_module.app) as client:
        result=client.get('/api/v2/source-inventory').json()
        assert result['region_basis']=='collection_source'
        assert len(result['provinces'])==31 and len(result['sources'])==64
        blocked=[s for s in result['sources'] if s['status']=='blocked']
        assert len(blocked)==8 and all(s['blocker'] for s in blocked)
        assert len(client.get('/api/v2/regions').json())==32
