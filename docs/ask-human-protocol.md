# Ask-human 协议（ask-human/1）

agent 需要人拍板时（例如工厂给出最终报价），下发一张由内容块组成的问题卡，前端按能力和策略渲染，用户回答后服务端校验。

- 服务端：`src/smartlading/ask_human.py`（模型、`resolve_for_client`、`validate_answer`、示例 `final_offer_ask`）
- 前端：`web/src/lib/askHuman.ts`（类型、`CAPABILITIES`、同样的降级逻辑）、`web/src/components/ask/AskHuman.tsx`（渲染器注册表）
- 预览：dev server 上打开 `/ask-demo.html`

## 流程

```
client ──(X-Ask-Capabilities: ClientCapabilities JSON)──▶ server
server ── resolve_for_client(ask, caps) ──▶ AskHuman（只含客户端能渲染的块）
client ── 渲染 blocks，按 policy 选展示面 ──▶ 用户
client ──POST /api/v1/asks/{id}/answer  HumanAnswer──▶ server ── validate_answer ──▶ agent 继续
```

（上面两个 HTTP 约定是建议，`api.py` 里还没有对应路由。）

## 内容块

所有块都有 `id`、`type`、`version`（默认 1）。`text` 是基线，所有客户端必须支持。

| type | 用途 | 降级为 |
|---|---|---|
| `text` | 文字，`tone` = plain/info/warn/danger/success | — |
| `facts` | 指标格子（label/value/hint/tone） | text |
| `card` | 供应商/SKU 卡片：标题、徽章、图片、facts | text |
| `table` | 列定义 + 行，`highlight_row` | text（超过 `max_table_rows` 先截断） |
| `bill` | 账单/形式发票，合计由 lines 计算 | table → text |
| `image` | 图片 + alt + caption | text |
| `media` | 视频/音频，可带 poster | image（有 poster）→ text |
| `map` | markers + routes（sea/air/road） | table → text |

降级时块的 `id` 不变。新增块类型或给已有块升版本时，必须同时实现 `fallback()`（Python）和 `fallback()`（TS），老客户端才能看到等价内容。

## 能力协商

```json
{ "protocol": "ask-human/1", "blocks": {"text": 1, "table": 1, "bill": 1, "map": 1},
  "surfaces": ["inline", "modal"], "max_table_rows": 50 }
```

- 块的 `version` 高于客户端声明的版本（或未声明）就逐级降级，直到能渲染或成为 `text`。
- 协议大版本不同（`ask-human/2`）直接拒绝；小版本（`ask-human/1.3`）只加可选字段，兼容。
- `policy.surface` 不在 `surfaces` 里时退回 `inline`。

## 渲染策略 RenderPolicy

- `surface`：`inline`（嵌在对话里）/ `sheet`（侧栏）/ `modal`（对话框）
- `urgency`：`low` / `normal` / `blocking`（回答前暂停该会话的输入，modal 不能用 Esc 关闭）
- `expires_at` + `default_action_id`：过期后服务端按默认动作处理，过期的回答会被拒绝

## 回答

`response` 定义 `actions`（按钮，`style` = primary/secondary/danger，`requires_fields=false` 的动作如"拒绝"不检查必填）、`fields`（text/number/select/boolean，带 required/min/max/options）和 `allow_comment`。

`validate_answer` 会检查：ask_id 是否对得上、是否过期、动作是否存在、必填项、数值范围、select 的值是否在选项里、boolean 类型。未知字段会被丢掉，不允许备注时 comment 置空。前端的 `validate()` 只用来即时提示，以服务端校验为准。
