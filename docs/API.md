# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV。

## 签发与例外放行

角色仅支持 `提交人`、`复核人`，两类身份的权限在服务端强制分离，任何请求都必须带 `actor`（操作人标识）与 `role`。

| 接口 | 方法 | 角色 | 状态迁移 | 要点 |
|---|---|---|---|---|
| `/api/runs/<id>/review` | POST | 仅复核人 | 待复核/退回复核/例外放行 → 已签发；待复核 → 退回复核 | body 含 `version`、`decision`（已签发/退回复核） |
| `/api/runs/<id>/exception-release` | POST | 仅提交人 | 待复核/退回复核 → 例外放行 | body 含 `version`、`reason`（强制，留痕），自动置 `follow_up_required=true` |
| `/api/runs/<id>/signoffs` | GET | 不限 | — | 返回仅追加的签发事件链 |

规则：

1. 所有签发动作按 `version` 做条件更新；版本结论一旦变化，旧版本提交返回 409 `STALE_VERSION`，原签发凭据与旧版本绑定、不能用于新版本。
2. `已签发` 为终态：再复核或再走例外通道返回 422 `ALREADY_SIGNED`；同一批次例外放行只能一次（`ALREADY_EXCEPTION`）。角色越权返回 422 `ROLE_FORBIDDEN`。
3. 例外放行后复核人到岗补复核走 review 通道，事件类型记为 `复核补签`，沿用同一 `credential_id` 锚点但产生新的动作签章，并解除 `follow_up_required`。
4. 签发凭据（credential_id + HMAC-SHA256 seal）只存一份于 runs 表与 signoff_events 事件链；页面 `/api/runs/<id>` 与 `/api/runs/<id>/archive` 读取同一存储。未签发批次的导出不含凭据，仅写一行 `未签发：无凭据，待复核`。
5. 同源重跑走 `INSERT OR IGNORE` 复用原批次行，不新增也不改换签署；待复核、例外放行、已签发各自状态独立保留。
