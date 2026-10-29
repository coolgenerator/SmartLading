# SmartLading MVP：字段、功能映射与 API 设计

> 依据 [PRD.md](PRD.md)。技术栈假设：Python 3.12 + Pydantic v2（已在 `pyproject.toml`）+ FastAPI（待加）+ Anthropic SDK。
> 标注 **[假设]** 的地方是对 PRD「开放问题」给出的 MVP 默认值，可随时改。

---

## 1. 关键字段

约定：金额统一 USD（`float`，MVP 不做多币种）；比例 0–1；天数为整数；`id` 为字符串（`brand_xxx`、`sku_xxx` 前缀便于调试）。

### 1.1 核心实体（PRD 7 个）

#### Brand —— 租户/品牌（F1）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str | 租户 ID |
| `name` | str | |
| `cash_balance` | float | 当前现金 C₀ |
| `credit_limit` | float | 授信额度；现金 < 0 时先动用，用尽 = 现金断裂 |
| `cash_safety_line` | float | 现金安全线；跑道 = 首次低于它的天数 |
| `safety_line_mode` | `"fixed" \| "days_of_fixed_cost"` | **[假设]** 两种都支持，默认 `days_of_fixed_cost` |
| `safety_line_days` | int \| null | mode=days 时使用，安全线 = N × `daily_fixed_cost` |
| `daily_fixed_cost` | float | F，每日固定成本 |
| `state_version` | int | 任何状态字段修改 +1，用于判定模拟结果"已过期" |

#### SKU（F1、F2）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `brand_id` | str | |
| `name` / `category` | str | category 用于匹配 M5 需求模板 |
| `price` | float | P，售价 |
| `unit_platform_fee` | float | m，单位平台 + 履约费用 |
| `on_hand` | int | I₀，当前库存 |
| `hts_code` | str | 关税编码，F3 信号按此匹配 |
| `tariff_rate` | float | 当前税率 τ（来自 HTS + 已接受信号） |
| `demand_template_id` | str | 指向 M5 参考序列 |
| `demand_scale` | float | 按品牌规模的缩放系数 |

#### Supplier（F1、F2、F6）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `brand_id` | str | |
| `name` / `country` | str | |
| `lead_time_mean_days` | float | 交期 L 的均值（对数正态） |
| `lead_time_std_days` | float | 交期波动 |
| `moq` | int | 最低订货量 |
| `default_prepay_ratio` | float | 默认 α |
| `risk_score` | float (0–1) | 风险评分 |
| `default_prob` | float（派生） | r = f(risk_score)；**[假设]** MVP 用线性 `r = 0.2 × risk_score`（评分 1 → 20% 违约） |

#### SupplierOffer（F2、F6）

| 字段 | 类型 | 说明 |
|---|---|---|
| `sku_id` / `supplier_id` | str | 联合主键 |
| `unit_cost` | float | c |
| `unit_freight` | float | f |

#### PurchaseOrder（F1、F2、F5）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `brand_id` / `sku_id` / `supplier_id` | str | |
| `quantity` | int | Q |
| `prepay_ratio` | float | α |
| `order_date` | date | 下单日 |
| `ship_date` / `eta` | date \| null | 出货日 / 预计到港日 |
| `status` | `"planned" \| "in_transit" \| "arrived"` | 在途订单参与模拟（未来到货 + 未付尾款/关税） |

#### Scenario —— 一次方案比较（F2、F4）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `brand_id` | str | |
| `sku_id` / `supplier_id` | str | 关联"待下的采购单" |
| `options` | `list[ScenarioOption]`（2–3 个） | 见下 |
| `seed` | int | 固定随机种子 |
| `horizon_days` | int | 默认 120 |
| `n_paths` | int | 默认 1000 |
| `state_version` | int | 运行时的 Brand.state_version |
| `input_hash` | str | 全部输入（状态快照 + 参数）的哈希，用于复现校验 |
| `result` | `SimulationResult \| null` | |
| `recommendation` | `Recommendation \| null` | |
| `selected_option_id` | str \| null | 用户最终选的方案（US-6） |
| `is_stale` | bool（派生） | `state_version != brand.state_version` |

`ScenarioOption`：`id`、`label`（如"A"）、`quantity`、`prepay_ratio`（可空，空则用供应商默认）。

#### RiskSignal（F3）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `brand_id` | str | |
| `source_text` | str | 原文全文 |
| `source_type` | `"tariff" \| "supplier_news" \| "other"` | |
| `quote` | str | 必须是 `source_text` 的子串（服务端校验） |
| `quote_span` | `[start, end]` | 原文中的字符偏移，前端高亮用 |
| `target_type` | `"hts_code" \| "supplier" \| "sku"` | 影响对象类型 |
| `target_id` | str | HTS 编码 / supplier_id / sku_id |
| `parameter` | enum | `tariff_rate`、`lead_time_mean_days`、`lead_time_std_days`、`default_prob`、`unit_cost`、`unit_freight`、`moq`、`prepay_ratio` |
| `change_type` | `"set" \| "delta" \| "multiply"` | 如税率设为 0.25 / 交期 +14 天 / 成本 ×1.1 |
| `change_value` | float | |
| `probability` | float | 发生概率 p；**[假设]** LLM 给 `llm_probability` 参考，用户最终确认 `probability` |
| `llm_probability` | float \| null | LLM 建议值 |
| `effective_date` | date \| null | 生效日（模拟中第几天跳变） |
| `status` | `"pending" \| "accepted" \| "rejected"` | 只有 accepted 进入模拟 |
| `edited_by_user` | bool | 是否被修改过 |

### 1.2 结果与辅助对象

#### SimulationResult / OptionMetrics（F2）

```
SimulationResult
  scenario_id, seed, input_hash, engine_version, elapsed_ms
  options: list[OptionMetrics]
  suggested: SuggestedQuantity | null      # 网格搜索结果（可选）

OptionMetrics
  option_id
  runway_p10 / runway_p50 / runway_p90: int   # 天；未触及记为 horizon_days + 1，前端显示 ">120"
  stockout_prob: float                         # 至少一天缺货的路径占比
  expected_profit: float                       # 120 天利润均值
  worst_case_p5: float                         # 利润 P5
  credit_breach_prob: float                    # 授信用尽的路径占比（辅助）
  default_loss_prob: float                     # 供应商违约发生占比（辅助，用于"主要风险来源"）
  risk_attribution: dict[str, float]           # 各风险源对 P5 的贡献（需求/交期/关税/违约），供 F4 解释
  cash_fan: CashFan

CashFan
  days: list[int]            # 0..horizon
  p10 / p50 / p90: list[float]
  safety_line: float
```

`SuggestedQuantity`：`quantity`、`prepay_ratio`、`metrics: OptionMetrics`、`grid: list[{quantity, expected_profit, runway_p10}]`。

#### Recommendation / Explanation（F4）

```
Recommendation                          # 纯规则，引擎侧计算
  recommended_option_id
  rule: "max_profit_under_runway_constraint" | "min_risk_fallback"
  feasible_option_ids: list[str]        # runway_p10 >= 安全线的方案
  warning: str | null                   # 无方案满足约束时
  counterfactual_option_id              # 反事实对比用的方案

Explanation                             # LLM 叙述
  status: "ok" | "rejected_number_mismatch" | "llm_error" | "pending"
  text: str | null                      # 校验不通过则为 null，不展示
  sections: {reason, main_risks, counterfactual}
  cited_numbers: list[{value: float, metric_path: str}]   # 如 "options[A].worst_case_p5"
  model: str, latency_ms: int
```

数字可追溯实现：给 LLM 的输入是一张"允许引用的数字表"（metric_path → 格式化后的值），要求它只能引用表中项；服务端从 `text` 中正则抽出所有数字，逐一匹配表中值（考虑格式化/四舍五入），有任何一个对不上 → `rejected_number_mismatch`。

#### Event / Alert（F5，P1）

```
PresetEvent:  id, name, description, signals: list[RiskSignal 模板]   # 例："关税上调至 25%"、"供应商 B 延期 21 天"
Alert:        id, event_id, purchase_order_id, extra_cost, cash_gap, message, next_step, created_at, acknowledged
```

#### Negotiation（F6，P1）

```
Negotiation:   id, supplier_id, sku_id, base_scenario_id, status("open"|"agreed"|"walked_away"), turns
FactoryPersona (服务端私有，不下发前端):
               min_prepay_ratio, min_quantity, min_unit_cost, preferences(权重)
Terms:         prepay_ratio, quantity, unit_cost
NegotiationTurn:
               role("user"|"factory"), message, proposed_terms: Terms, impact: OptionMetrics | null
```

底线约束在服务端硬校验：LLM 给出的 counter terms 若越过底线则夹回底线，不依赖 prompt。

#### Demo（非功能）

`Vote`：`id`、`demo_point`（1/2/3）、`choice`、`created_at`。

---

## 2. 功能 ↔ 字段 ↔ 页面 ↔ API 映射

| 功能 | 优先级 | 用户故事 | 读写的实体/字段 | 页面 | API |
|---|---|---|---|---|---|
| F1 业务状态模型 | P0 | — | Brand、SKU、Supplier、SupplierOffer、PurchaseOrder；写入时 `state_version += 1` | 品牌概览 | §3.1 |
| F2 采购决策模拟器 | P0 | US-1、US-2、US-6 | Scenario、ScenarioOption、SimulationResult、CashFan | 决策工作台 | §3.2 |
| F3 风险信号提取 | P0 | US-4、US-5 | RiskSignal（accept 时改写 SKU.tariff_rate / Supplier.* 并 bump 版本） | 风险信号 | §3.3 |
| F4 建议与解释 | P0 | US-3、US-6 | Recommendation、Explanation、OptionMetrics.risk_attribution | 决策工作台 | §3.4 |
| F5 事件注入与预警 | P1 | US-7 | PresetEvent、Alert、PurchaseOrder（在途） | 品牌概览（预警入口） | §3.5 |
| F6 供应商谈判模拟 | P1 | US-8 | Negotiation、FactoryPersona、Terms | 谈判室 | §3.6 |
| Demo 模式 | — | — | 全部 seed 数据、Vote | 全局 | §3.7 |

**交互要求 → 实现方式**

| 交互要求 | 实现 |
|---|---|
| 参数变化后结果标"已过期" | `GET /scenarios/{id}` 返回 `is_stale`；前端在任何 PATCH/accept 后 refetch |
| 推荐 ≠ 用户选择时叠加两条 P50 曲线 | `PUT /scenarios/{id}/selection` 后，前端用两个 option 的 `cash_fan.p50` 叠加（数据已在 result 里，无需新接口） |
| 先出数字后出解释 | 模拟与解释拆成两个请求；解释失败不影响结果卡和图表 |

---

## 3. API 设计（REST，前缀 `/api/v1`）

MVP 单租户 Demo，`brand_id` 放路径中，为赛后多租户隔离留位。错误统一：`{"error": {"code": str, "message": str, "details": any}}`。

### 3.1 F1 业务状态

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/brands/{brand_id}` | 品牌概览聚合：brand + skus + suppliers + offers + purchase_orders + 未读 alerts 数 |
| PATCH | `/brands/{brand_id}` | 改现金、授信、安全线、固定成本 |
| GET | `/brands/{brand_id}/skus` | SKU 列表（库存表） |
| PATCH | `/brands/{brand_id}/skus/{sku_id}` | 改售价、库存、税率等 |
| GET | `/brands/{brand_id}/suppliers` | 供应商卡片 |
| PATCH | `/brands/{brand_id}/suppliers/{supplier_id}` | 改交期、MOQ、预付比例、风险评分（验收点） |
| GET | `/brands/{brand_id}/skus/{sku_id}/offers` | 该 SKU 的各供应商报价 |
| GET / POST | `/brands/{brand_id}/purchase-orders` | 在途/计划订单列表、新建 |
| PATCH | `/brands/{brand_id}/purchase-orders/{po_id}` | 改状态/数量 |

所有 PATCH 响应带新的 `state_version`。

```http
PATCH /api/v1/brands/b1/suppliers/s2
{"lead_time_mean_days": 45, "risk_score": 0.6}
→ 200 {"supplier": {...}, "state_version": 8}
```

### 3.2 F2 模拟

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/brands/{brand_id}/scenarios` | 创建并同步运行（目标 < 2s） |
| GET | `/brands/{brand_id}/scenarios/{scenario_id}` | 结果 + `is_stale` |
| POST | `/brands/{brand_id}/scenarios/{scenario_id}/run` | 用当前状态重新运行（"已过期"后点击） |
| PATCH | `/brands/{brand_id}/scenarios/{scenario_id}` | 修改方案列表/种子（会清空 result） |
| POST | `/brands/{brand_id}/scenarios/{scenario_id}/optimize` | Q 网格搜索 → `suggested` |
| PUT | `/brands/{brand_id}/scenarios/{scenario_id}/selection` | 记录用户选择的 option |

```http
POST /api/v1/brands/b1/scenarios
{
  "sku_id": "sku_07", "supplier_id": "s2",
  "options": [
    {"label": "A", "quantity": 3000},
    {"label": "B", "quantity": 5000, "prepay_ratio": 0.3},
    {"label": "C", "quantity": 8000}
  ],
  "seed": 42, "horizon_days": 120, "n_paths": 1000
}
→ 201
{
  "id": "scn_01", "state_version": 8, "is_stale": false, "input_hash": "…",
  "result": {
    "elapsed_ms": 830,
    "options": [
      {"option_id": "opt_A", "runway_p10": 74, "runway_p50": 121, "runway_p90": 121,
       "stockout_prob": 0.41, "expected_profit": 182000, "worst_case_p5": -15000,
       "risk_attribution": {"demand": 0.5, "lead_time": 0.3, "tariff": 0.1, "default": 0.1},
       "cash_fan": {"days": [0, …, 120], "p10": […], "p50": […], "p90": […], "safety_line": 60000}}
    ]
  },
  "recommendation": {"recommended_option_id": "opt_B", "rule": "max_profit_under_runway_constraint", …}
}
```

校验：options 2–3 个；quantity ≥ supplier.moq（否则 422 并提示）；同一 `input_hash` + `seed` 必须产生逐位一致结果（写测试）。

### 3.3 F3 风险信号

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/brands/{brand_id}/risk-signals/extract` | LLM 提取，生成 `pending` 信号 |
| GET | `/brands/{brand_id}/risk-signals?status=pending` | 列表 |
| PATCH | `/brands/{brand_id}/risk-signals/{signal_id}` | 修改 change_value / probability / target / effective_date |
| POST | `/brands/{brand_id}/risk-signals/{signal_id}/accept` | 写入状态模型，bump `state_version` |
| POST | `/brands/{brand_id}/risk-signals/{signal_id}/reject` | |
| GET | `/brands/{brand_id}/risk-signals/samples` | Demo 预置新闻文本（"选择一条文本"） |

```http
POST /api/v1/brands/b1/risk-signals/extract
{"text": "USTR announced … tariffs on HTS 9403.60 will rise to 25% effective Jan 1 …", "source_type": "tariff"}
→ 200
{
  "status": "found",                    // 或 "no_quantifiable_impact"，此时 signals = []
  "message": null,                      // no_quantifiable_impact 时为 "未发现可量化的影响"
  "signals": [
    {"id": "sig_01", "quote": "tariffs on HTS 9403.60 will rise to 25%", "quote_span": [22, 61],
     "target_type": "hts_code", "target_id": "9403.60", "parameter": "tariff_rate",
     "change_type": "set", "change_value": 0.25, "llm_probability": 0.7, "probability": 0.7,
     "effective_date": "2027-01-01", "status": "pending",
     "affected_skus": ["sku_03", "sku_07"]}
  ]
}
```

服务端硬校验：`quote` 不是原文子串的信号直接丢弃；`target_id` 在品牌数据中不存在的标为未匹配；LLM 用 tool use 输出结构化 JSON（Pydantic schema）。

**accept 后的模拟语义**：带 `probability < 1` 的信号进入引擎的跳变模型（每条路径以 p 在 `effective_date` 跳到新值），而不是直接覆盖基础字段；`probability = 1` 时等价于直接修改。

### 3.4 F4 建议与解释

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/brands/{brand_id}/scenarios/{scenario_id}/recommendation` | 规则推荐（也随 scenario 一起返回） |
| POST | `/brands/{brand_id}/scenarios/{scenario_id}/explanation` | 生成 LLM 解释（目标 < 5s），可选 `?stream=true` 走 SSE |

```http
POST /api/v1/brands/b1/scenarios/scn_01/explanation
→ 200
{
  "status": "ok",
  "text": "推荐方案 B：在现金跑道 P10 为 96 天、高于安全线的前提下，预期利润 $214,000 最高……如果选 C，最坏情况下利润为 -$88,000……",
  "sections": {"reason": "…", "main_risks": "…", "counterfactual": "…"},
  "cited_numbers": [{"value": 96, "metric_path": "options[opt_B].runway_p10"}, …]
}
// 校验失败：{"status": "rejected_number_mismatch", "text": null}，前端只显示数字结果
// LLM 失败：{"status": "llm_error", "text": null}
```

scenario 已过期时返回 409 `scenario_stale`，避免对旧数字生成解释。

### 3.5 F5 事件与预警（P1）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/brands/{brand_id}/events` | 预设事件列表 |
| POST | `/brands/{brand_id}/events/{event_id}/inject` | 应用事件（以 accepted 信号形式写入）→ 重算受影响在途订单 → 生成预警 |
| GET | `/brands/{brand_id}/alerts?acknowledged=false` | 预警列表 |
| POST | `/brands/{brand_id}/alerts/{alert_id}/ack` | 标记已读 |

```http
POST /api/v1/brands/b1/events/evt_tariff_25/inject
→ 200 {"state_version": 9, "alerts": [{"purchase_order_id": "po_12", "extra_cost": 18400, "cash_gap": 6200,
        "message": "…", "next_step": "考虑将尾款期延后或提前出货"}], "stale_scenario_ids": ["scn_01"]}
```

### 3.6 F6 谈判（P1）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/brands/{brand_id}/negotiations` | 开启谈判 `{supplier_id, sku_id, base_scenario_id}` |
| GET | `/brands/{brand_id}/negotiations/{negotiation_id}` | 对话历史 + 当前条款 |
| POST | `/brands/{brand_id}/negotiations/{negotiation_id}/turns` | 用户出价 → 工厂回应 + 新条款的模拟影响 |

```http
POST /api/v1/brands/b1/negotiations/neg_01/turns
{"message": "预付能降到 20% 吗？我们可以订 6000 件", "proposed_terms": {"prepay_ratio": 0.2, "quantity": 6000, "unit_cost": 4.1}}
→ 200
{
  "factory_reply": {"message": "20% 不行，最低 25%，6000 件可以给 4.2", "counter_terms": {"prepay_ratio": 0.25, "quantity": 6000, "unit_cost": 4.2}},
  "impact": {"base": OptionMetrics, "proposed": OptionMetrics, "counter": OptionMetrics}   // 用同一 seed 跑
}
```

### 3.7 Demo / 系统

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/demo/seed` | 加载虚构品牌（20 SKU、3 供应商），返回 `brand_id` |
| POST | `/demo/reset` | 恢复到初始 seed 状态 |
| POST | `/demo/votes` | 评委投票 |
| GET | `/demo/votes/summary` | 投票统计 |
| GET | `/health` | 含 LLM 可用性，前端据此决定是否显示解释区 |

---

## 4. 建议的代码结构

```
src/smartlading/
  models/          # Pydantic：entities.py（7 实体）、results.py、signals.py、negotiation.py
  engine/          # 纯 numpy，无 IO：simulate.py、demand.py（M5 bootstrap）、recommend.py、optimize.py
  llm/             # extract_signals.py、explain.py、negotiate.py、number_check.py
  store/           # MVP 内存/SQLite 仓储 + seed 数据
  api/             # FastAPI 路由，按 §3 分文件
data/              # M5 抽样后的需求模板、seed_brand.json、preset_events.json、sample_news/
tests/             # 重点：引擎可复现性、推荐规则、数字校验、quote 子串校验
```

引擎与 LLM 完全解耦：`engine` 只吃状态快照 + 已接受信号，输出 `SimulationResult`；这样"LLM 失败时模拟器仍可用"天然成立，也便于逐位复现测试。
