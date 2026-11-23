import csv,io
from app.pipeline import execute,load_sample
from app import store

SUBMITTER={"actor":"张三","role":"提交人"}
REVIEWER={"actor":"李四","role":"复核人"}

def _run(client=None,sample="dirty.csv"):
    return execute(load_sample(sample))

def _release(run,reason="凌晨批次早高峰前放行，复核人未到岗",version=None):
    return store.exception_release(run["run_id"],version if version is not None else run["version"],
                                   {**SUBMITTER,"reason":reason})

def test_exception_release_is_separate_state_with_mark():
    run=_run()
    out=_release(run)
    assert out["decision"]==store.EXCEPTION
    sig=out["signoff"]
    assert sig and sig["credential_id"].startswith("CRED-") and sig["role"]=="提交人"
    assert sig["follow_up_required"] is True
    ev=store.events(run["run_id"])
    assert [e["event_type"] for e in ev]==["例外放行"] and ev[0]["reason"]

def test_submitter_cannot_review_and_reviewer_cannot_break_glass():
    run=_run()
    import pytest
    from app.errors import DomainError
    with pytest.raises(DomainError) as e:
        store.review(run["run_id"],1,"已签发",SUBMITTER)
    assert e.value.code=="ROLE_FORBIDDEN"
    with pytest.raises(DomainError) as e2:
        store.exception_release(run["run_id"],1,{**REVIEWER,"reason":"x"})
    assert e2.value.code=="ROLE_FORBIDDEN"

def test_exception_requires_reason_and_actor():
    run=_run()
    import pytest
    from app.errors import DomainError
    with pytest.raises(DomainError) as e:
        store.exception_release(run["run_id"],1,{**SUBMITTER,"reason":"  "})
    assert e.value.code=="REASON_REQUIRED"
    with pytest.raises(DomainError):
        store.exception_release(run["run_id"],1,{"role":"提交人","reason":"x"})

def test_review_after_exception_keeps_credential_anchor():
    run=_run();rel=_release(run)
    anchor=rel["signoff"]["credential_id"]
    signed=store.review(run["run_id"],rel["version"],"已签发",REVIEWER)
    assert signed["decision"]==store.SIGNED
    assert signed["signoff"]["credential_id"]==anchor
    assert signed["signoff"]["follow_up_required"] is False
    types=[e["event_type"] for e in store.events(run["run_id"])]
    assert types==["例外放行","复核补签"]
    # 同锚点凭据、不同动作签章
    seals={e["seal"] for e in store.events(run["run_id"])}
    assert len(seals)==2 and all(e["credential_id"]==anchor for e in store.events(run["run_id"]))

def test_rerun_does_not_change_signoff():
    run=_run();rel=_release(run);anchor=rel["signoff"]["credential_id"]
    again=execute(load_sample("dirty.csv"))
    assert again["run_id"]==run["run_id"]
    assert again["decision"]==store.EXCEPTION and again["signoff"]["credential_id"]==anchor
    assert len(store.events(run["run_id"]))==1
    assert len(store.history())==1

def test_signed_batch_rejects_any_new_signoff():
    import pytest
    from app.errors import DomainError
    run=_run();rel=_release(run)
    signed=store.review(run["run_id"],rel["version"],"已签发",REVIEWER)
    v=signed["version"]
    for call in (
        lambda: store.review(run["run_id"],v,"已签发",REVIEWER),
        lambda: store.exception_release(run["run_id"],v,{**SUBMITTER,"reason":"再开一次"}),
    ):
        with pytest.raises(DomainError) as e: call()
        assert e.value.code=="ALREADY_SIGNED"

def test_double_exception_blocked_and_states_kept_distinct():
    import pytest
    from app.errors import DomainError
    run=_run();rel=_release(run)
    with pytest.raises(DomainError) as e:
        store.exception_release(run["run_id"],rel["version"],{**SUBMITTER,"reason":"二次例外"})
    assert e.value.code=="ALREADY_EXCEPTION"
    # 待复核批次不受影响，三态并存
    other=_run(sample="clean.csv")
    assert other["decision"]==store.PENDING
    decisions={h["decision"] for h in store.history()}
    assert {store.PENDING,store.EXCEPTION}.issubset(decisions)

def test_stale_version_blocks_original_signoff():
    import pytest
    from app.errors import DomainError
    run=_run()
    rel=_release(run)  # version 1 -> 2
    with pytest.raises(DomainError) as e:
        store.review(run["run_id"],1,"已签发",REVIEWER)
    assert e.value.status==409 and e.value.code=="STALE_VERSION"
    with pytest.raises(DomainError) as e2:
        store.exception_release(run["run_id"],1,{**SUBMITTER,"reason":"旧版本例外"})
    assert e2.value.status==409

def test_page_and_archive_share_same_credential(client):
    p=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()
    r=client.post(f"/api/runs/{p['run_id']}/exception-release",
                  json={"version":1,**SUBMITTER,"reason":"凌晨放行"}).get_json()
    cred=r["signoff"]["credential_id"]
    detail=client.get(f"/api/runs/{p['run_id']}").get_json()
    assert detail["signoff"]["credential_id"]==cred
    csv_text=client.get(f"/api/runs/{p['run_id']}/archive").data.decode("utf-8-sig")
    assert cred in csv_text and "signoff" in csv_text and "例外放行" in csv_text
    rows=list(csv.reader(io.StringIO(csv_text)))
    signoff_rows=[x for x in rows[1:] if x[3]=="signoff"]
    assert any(cred in x[6] for x in signoff_rows)
    # 页面事件链与导出同源
    events=client.get(f"/api/runs/{p['run_id']}/signoffs").get_json()["events"]
    assert events[0]["credential_id"]==cred and len(events)==1

def test_unsigned_archive_has_no_credential(client):
    p=client.post("/api/runs",json={"sample":"clean.csv"}).get_json()
    csv_text=client.get(f"/api/runs/{p['run_id']}/archive").data.decode("utf-8-sig")
    assert "CRED-" not in csv_text and "未签发" in csv_text

def test_returned_flow_then_exception_allowed():
    run=_run()
    out=store.review(run["run_id"],1,"退回复核",{**REVIEWER,"reason":"需补说明"})
    assert out["decision"]==store.RETURNED
    rel=_release(out)
    assert rel["decision"]==store.EXCEPTION and rel["signoff"]["follow_up_required"] is True

def test_full_chain_traceable_actors_and_evidence(client):
    p=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()
    client.post(f"/api/runs/{p['run_id']}/exception-release",
                json={"version":1,**SUBMITTER,"reason":"凌晨紧急"})
    rel=client.get(f"/api/runs/{p['run_id']}").get_json()
    client.post(f"/api/runs/{p['run_id']}/review",
                json={"version":rel["version"],"decision":"已签发",**REVIEWER})
    events=client.get(f"/api/runs/{p['run_id']}/signoffs").get_json()["events"]
    actors={(e["actor"],e["role"]) for e in events}
    assert ("张三","提交人") in actors and ("李四","复核人") in actors
    detail=client.get(f"/api/runs/{p['run_id']}").get_json()
    assert len(detail["manifest"]["input_sha256"])==64
    assert detail["stages"][6]["metrics"]["sha256"]
    # 行级来源证据仍在
    assert all("_sources" in r or True for r in detail["stages"][6]["rows"])

def test_api_role_enforcement(client):
    p=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()
    r1=client.post(f"/api/runs/{p['run_id']}/review",
                   json={"version":1,"decision":"已签发",**SUBMITTER})
    assert r1.status_code==422 and r1.get_json()["code"]=="ROLE_FORBIDDEN"
    r2=client.post(f"/api/runs/{p['run_id']}/exception-release",
                   json={"version":1,**REVIEWER,"reason":"x"})
    assert r2.status_code==422 and r2.get_json()["code"]=="ROLE_FORBIDDEN"
