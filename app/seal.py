import hashlib,hmac,os
from datetime import datetime,timezone
from app.config import DATA_DIR

# 单机工具不引入登录体系：签章密钥在数据目录首次启动时生成并固定，
# 页面与回补导出共用同一把密钥、同一份存储凭据，保证两边可互验。
def _secret_key():
    path=DATA_DIR/"seal.key"
    if not path.exists():
        DATA_DIR.mkdir(parents=True,exist_ok=True)
        path.write_bytes(os.urandom(32))
        os.chmod(path,0o600)
    return path.read_bytes()

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def sign(run,event_type,actor,role,reason,from_version,to_version):
    """对一次签发动作生成确定性凭据：证据摘要+状态迁移+操作人共同入签。"""
    evidence=run["manifest"]["input_sha256"]
    rule_version=run["manifest"]["rule_version"]
    m7=run["stages"][-1]["metrics"]
    basis="|".join([
        run["run_id"],str(from_version),str(to_version),event_type,
        actor or "",role or "",reason or "",evidence,rule_version,
        str(m7.get("records","")),m7.get("sha256",""),
    ])
    digest=hmac.new(_secret_key(),basis.encode(),hashlib.sha256).hexdigest()
    credential_id="CRED-"+digest[:16].upper()
    return credential_id,digest,utc_now()
