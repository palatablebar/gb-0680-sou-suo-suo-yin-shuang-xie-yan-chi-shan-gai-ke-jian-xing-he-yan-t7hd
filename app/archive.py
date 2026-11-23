import csv,io,json
def build_archive(run,events=None):
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["run_id","input_sha256","rule_version","kind","source_lines","reason","evidence"])
    meta=run["manifest"]
    for row in run["stages"][-1]["rows"]:
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"accepted",json.dumps(row.get("_sources",[])),row.get("status",""),json.dumps(row,ensure_ascii=False)])
    for row in run["stages"][-1].get("cumulative_quarantine",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"quarantine",json.dumps(row.get("_sources",[])),row.get("reason",""),json.dumps(row,ensure_ascii=False)])
    # 签发区：页面与导出共用存储中的同一份凭据；未签发批次显式留痕，不伪造签章
    events=events or []
    for ev in events:
        evidence={"event_type":ev["event_type"],"actor":ev["actor"],"role":ev["role"],
                  "from_version":ev["from_version"],"to_version":ev["to_version"],"decision":ev["decision"],
                  "credential_id":ev["credential_id"],"seal":ev["seal"],"sealed_at":ev["sealed_at"],
                  "follow_up_required":ev["follow_up_required"]}
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"signoff",
                         f'{ev["from_version"]}->{ev["to_version"]}',ev.get("reason") or "",
                         json.dumps(evidence,ensure_ascii=False)])
    if not events:
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"signoff","",
                         "未签发：无凭据，待复核",json.dumps({"decision":run["decision"]},ensure_ascii=False)])
    return "﻿"+stream.getvalue()
