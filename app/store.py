import sqlite3,json
from app.config import DATA_DIR
from app.errors import DomainError
from app import seal

PENDING="待复核";EXCEPTION="例外放行";SIGNED="已签发";RETURNED="退回复核"
ROLE_SUBMITTER="提交人";ROLE_REVIEWER="复核人"
REVIEWER_DECISIONS={SIGNED,RETURNED}
_SIGNOFF_COLUMNS=["signoff_credential_id","signoff_seal","signoff_at","signoff_actor","signoff_role","follow_up_required"]

def connect():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA_DIR/"records.db",timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核')")
    existing={r[1] for r in db.execute("PRAGMA table_info(runs)")}
    for column in _SIGNOFF_COLUMNS:
        if column not in existing:
            default=" INTEGER NOT NULL DEFAULT 0" if column=="follow_up_required" else " TEXT"
            db.execute(f"ALTER TABLE runs ADD COLUMN {column}{default}")
    db.execute("""CREATE TABLE IF NOT EXISTS signoff_events(
        seq INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,event_type TEXT NOT NULL,
        actor TEXT NOT NULL,role TEXT NOT NULL,reason TEXT,from_version INTEGER NOT NULL,to_version INTEGER NOT NULL,
        decision TEXT NOT NULL,credential_id TEXT NOT NULL,seal TEXT NOT NULL,sealed_at TEXT NOT NULL,
        follow_up_required INTEGER NOT NULL DEFAULT 0)""")
    return db

def save(run_id,payload):
    # 同源重跑走 INSERT OR IGNORE：批次行与其签发事件链均不被覆盖或改换
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO runs(id,payload) VALUES (?,?)",(run_id,json.dumps(payload,ensure_ascii=False)))
    return get(run_id)

def _row_to_run(row):
    # _SELECT 列序：id,payload,version,decision,credential_id,seal,sealed_at,actor,role,follow_up_required
    run={**json.loads(row[1]),"version":row[2],"decision":row[3]}
    run["signoff"]={"credential_id":row[4],"seal":row[5],"sealed_at":row[6],
                    "actor":row[7],"role":row[8],"follow_up_required":bool(row[9])} if row[4] else None
    return run

def get(run_id):
    with connect() as db:
        row=db.execute(f"SELECT id,payload,version,decision,{','.join(_SIGNOFF_COLUMNS)} FROM runs WHERE id=?",(run_id,)).fetchone()
    if not row: raise DomainError("NOT_FOUND","批次不存在",404)
    return _row_to_run(row)

def latest():
    with connect() as db: row=db.execute("SELECT id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    return get(row[0]) if row else None

def history():
    with connect() as db:
        rows=db.execute(f"SELECT id,version,decision,{','.join(_SIGNOFF_COLUMNS)} FROM runs ORDER BY rowid DESC").fetchall()
    return [{"run_id":r[0],"version":r[1],"decision":r[2],
             "signoff_credential_id":r[3],"follow_up_required":bool(r[7])} for r in rows]

def events(run_id):
    get(run_id)
    with connect() as db:
        rows=db.execute("""SELECT seq,event_type,actor,role,reason,from_version,to_version,decision,
                                  credential_id,seal,sealed_at,follow_up_required
                           FROM signoff_events WHERE run_id=? ORDER BY seq""",(run_id,)).fetchall()
    keys=["seq","event_type","actor","role","reason","from_version","to_version","decision",
          "credential_id","seal","sealed_at","follow_up_required"]
    return [dict(zip(keys,r),follow_up_required=bool(r[-1])) for r in rows]

def _parse_actor(p):
    actor=p.get("actor");role=p.get("role")
    if not isinstance(actor,str) or not actor.strip(): raise DomainError("BAD_ACTOR","请提供操作人标识")
    if role not in {ROLE_SUBMITTER,ROLE_REVIEWER}: raise DomainError("BAD_ROLE","角色仅支持 提交人 / 复核人")
    return actor.strip(),role

def _assert_current_version(db,run_id,version):
    row=db.execute("SELECT version FROM runs WHERE id=?",(run_id,)).fetchone()
    if not row: raise DomainError("NOT_FOUND","批次不存在",404)
    # 版本结论一旦变化，任何旧版本签发一律先阻断（409），不进入后续角色/状态判断
    if row[0]!=version: raise DomainError("STALE_VERSION","版本结论已变化，原签发被阻断，请刷新",409)

def _apply_signoff(db,row,run_id,version,decision,event_type,actor,role,reason,follow_up):
    to_version=version+1
    run=_row_to_run(row)
    credential_id,digest,sealed_at=seal.sign(run,event_type,actor,role,reason,version,to_version)
    # 例外放行后的复核补签沿用同一凭据锚点，状态流转但签发凭据不更换
    anchor=row[4] or credential_id
    db.execute("""INSERT INTO signoff_events(run_id,event_type,actor,role,reason,from_version,to_version,
                  decision,credential_id,seal,sealed_at,follow_up_required)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
               (run_id,event_type,actor,role,reason,version,to_version,decision,anchor,digest,sealed_at,int(follow_up)))
    cursor=db.execute("""UPDATE runs SET version=?,decision=?,signoff_credential_id=?,signoff_seal=?,signoff_at=?,
                         signoff_actor=?,signoff_role=?,follow_up_required=? WHERE id=? AND version=?""",
                      (to_version,decision,anchor,digest,sealed_at,actor,role,int(follow_up),run_id,version))
    if cursor.rowcount!=1: raise DomainError("STALE_VERSION","版本结论已变化，原签发被阻断，请刷新",409)

_SELECT=f"SELECT id,payload,version,decision,{','.join(_SIGNOFF_COLUMNS)} FROM runs"

def review(run_id,version,decision,p):
    """复核通道：仅复核人。例外放行批次的事后补复核也走这里，不更换凭据。"""
    actor,role=_parse_actor(p)
    if role!=ROLE_REVIEWER: raise DomainError("ROLE_FORBIDDEN","提交人与复核人权限不可混用：复核签发仅复核人可执行",422)
    if decision not in REVIEWER_DECISIONS: raise DomainError("BAD_DECISION","复核状态无效",422)
    reason=p.get("reason")
    if reason is not None and not isinstance(reason,str): raise DomainError("BAD_REASON","理由需要文本")
    with connect() as db:
        _assert_current_version(db,run_id,version)
        row=db.execute(_SELECT+" WHERE id=?",(run_id,)).fetchone()
        current=row[3]
        if current==SIGNED: raise DomainError("ALREADY_SIGNED","批次已签发，状态与凭据不可改换",422)
        if decision==SIGNED and current not in {PENDING,EXCEPTION,RETURNED}:
            raise DomainError("ILLEGAL_TRANSITION",f"{current} 状态不可复核签发",422)
        if decision==RETURNED and current!=PENDING:
            raise DomainError("ILLEGAL_TRANSITION",f"仅 {PENDING} 批次可退回复核，当前为 {current}",422)
        event_type="复核补签" if current==EXCEPTION else "复核签发"
        _apply_signoff(db,row,run_id,version,decision,event_type,actor,role,reason,False)
    return get(run_id)

def exception_release(run_id,version,p):
    """例外通道（break-glass）：仅提交人，独立状态与例外印记，强制理由，事后必须补复核。"""
    actor,role=_parse_actor(p)
    if role!=ROLE_SUBMITTER: raise DomainError("ROLE_FORBIDDEN","例外放行仅提交人可发起，复核人不得代行提交职责",422)
    reason=p.get("reason")
    if not isinstance(reason,str) or not reason.strip(): raise DomainError("REASON_REQUIRED","例外放行必须填写业务理由与紧急情形",422)
    reason=reason.strip()
    with connect() as db:
        _assert_current_version(db,run_id,version)
        row=db.execute(_SELECT+" WHERE id=?",(run_id,)).fetchone()
        current=row[3]
        if current==SIGNED: raise DomainError("ALREADY_SIGNED","批次已签发，不可再走例外通道",422)
        if current==EXCEPTION: raise DomainError("ALREADY_EXCEPTION","批次已例外放行，不能重复或改换签署",422)
        if current not in {PENDING,RETURNED}: raise DomainError("ILLEGAL_TRANSITION",f"{current} 状态不可例外放行",422)
        _apply_signoff(db,row,run_id,version,EXCEPTION,"例外放行",actor,role,reason,True)
    return get(run_id)
