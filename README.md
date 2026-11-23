# 搜索索引双写延迟与删改可见性核验

供搜索数据同步值班工程师核对原始记录、处理差异并封存证据。

## 启动

```sh
docker compose up --build -d
docker compose exec -T app pytest -q
```

打开 http://localhost:18249 。首次进入自动运行仓内脏样例。工具条可重跑、切换样例或上传CSV。SQLite保存在命名卷records中，重建服务保留批次。

## 模块

- 1. 双端采信：`/streams`，`/api/streams`。
- 2. 字段契约：`/schema`，`/api/schema`。
- 3. 版本裁决：`/versions`，`/api/versions`。
- 4. 可见性重建：`/visibility`，`/api/visibility`。
- 5. 延迟闸门：`/latency`，`/api/latency`。
- 6. 双写对账：`/parity`，`/api/parity`。
- 7. 回补归档：`/backfills`，`/api/backfills`。

## 核心规则

按源版本重建目标可见状态，删除墓碑拦截迟到旧写入；延迟与缺失分开定责。

## 演示

1. 打开首页，核对当次计算、差异和隔离原因。
2. 切换模块查看源行及裁决依据。
3. 重跑相同样例，批次号与行数保持一致。
4. 选择角色后签发：复核人可复核签发；无人复核时提交人可走「例外放行」（强制填写理由，盖例外印记并标记事后补复核）。版本已变化的签发提交返回409。
5. 复核后导出一份证据CSV，签发行与页面共用同一份凭据；例外批次经复核补签后状态转已签发，凭据锚点不变。

## 输入与输出

输入列见 `docs/DATA-DICTIONARY.md`。项目包含dirty.csv、clean.csv、legacy.csv，统一走实际导入路径。上传限制4MB，拒绝不带时区的时间。业务键按字符串保留，Decimal参与计算，空值不会当零。

`POST /api/runs` 接收sample或csv；`GET /api/runs`返回历史批次；`POST /api/runs/<id>/review`需要version、decision、actor、role（仅复核人）；`POST /api/runs/<id>/exception-release`需要version、reason、actor、role（仅提交人）；`GET /api/runs/<id>/signoffs`返回签发事件链；`GET /api/runs/<id>/archive`返回唯一证据导出（含同一份签发凭据）。

## 范围

样例均为虚构。单机复核工具不连接生产系统；不提供登录、远端数据库或自动支付。内存计算按4MB输入上限控制，SQLite事务保证结果完整写入。

## 目录

app为服务与规则，sample_data为输入，tests为测试，docs为定义与深度登记。
