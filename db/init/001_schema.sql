-- SmartLading MVP schema，字段对应 docs/design.md §1。
-- 每张业务表带 brand_id，为赛后多租户隔离留位。
-- 嵌套的结果对象（模拟结果、推荐、解释、谈判轮次）存 JSONB，按 Pydantic 模型整体读写。

CREATE TABLE brands (
    id                 text PRIMARY KEY,
    name               text NOT NULL,
    cash_balance       double precision NOT NULL,
    credit_limit       double precision NOT NULL,
    cash_safety_line_fixed double precision,
    safety_line_mode   text NOT NULL DEFAULT 'days_of_fixed_cost'
                       CHECK (safety_line_mode IN ('fixed', 'days_of_fixed_cost')),
    safety_line_days   integer,
    daily_fixed_cost   double precision NOT NULL,
    state_version      integer NOT NULL DEFAULT 0
);

CREATE TABLE skus (
    id                 text PRIMARY KEY,
    brand_id           text NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    name               text NOT NULL,
    category           text NOT NULL DEFAULT '',
    price              double precision NOT NULL,
    unit_platform_fee  double precision NOT NULL,
    on_hand            integer NOT NULL,
    hts_code           text NOT NULL,
    tariff_rate        double precision NOT NULL,
    demand_template_id text NOT NULL DEFAULT '',
    demand_scale       double precision NOT NULL DEFAULT 1
);
CREATE INDEX skus_brand_idx ON skus (brand_id);

CREATE TABLE suppliers (
    id                   text PRIMARY KEY,
    brand_id             text NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    name                 text NOT NULL,
    country              text NOT NULL,
    lead_time_mean_days  double precision NOT NULL,
    lead_time_std_days   double precision NOT NULL,
    moq                  integer NOT NULL,
    default_prepay_ratio double precision NOT NULL CHECK (default_prepay_ratio BETWEEN 0 AND 1),
    risk_score           double precision NOT NULL CHECK (risk_score BETWEEN 0 AND 1)
);
CREATE INDEX suppliers_brand_idx ON suppliers (brand_id);

CREATE TABLE supplier_offers (
    sku_id        text NOT NULL REFERENCES skus(id) ON DELETE CASCADE,
    supplier_id   text NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    unit_cost     double precision NOT NULL,
    unit_freight  double precision NOT NULL,
    PRIMARY KEY (sku_id, supplier_id)
);

CREATE TABLE purchase_orders (
    id            text PRIMARY KEY,
    brand_id      text NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    sku_id        text NOT NULL REFERENCES skus(id),
    supplier_id   text NOT NULL REFERENCES suppliers(id),
    quantity      integer NOT NULL,
    prepay_ratio  double precision NOT NULL,
    order_date    date NOT NULL,
    ship_date     date,
    eta           date,
    status        text NOT NULL CHECK (status IN ('planned', 'in_transit', 'arrived'))
);
CREATE INDEX purchase_orders_brand_idx ON purchase_orders (brand_id, status);

CREATE TABLE scenarios (
    id                 text PRIMARY KEY,
    brand_id           text NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    sku_id             text NOT NULL REFERENCES skus(id),
    supplier_id        text NOT NULL REFERENCES suppliers(id),
    options            jsonb NOT NULL,
    seed               integer NOT NULL,
    horizon_days       integer NOT NULL DEFAULT 120,
    n_paths            integer NOT NULL DEFAULT 1000,
    state_version      integer NOT NULL,
    input_hash         text NOT NULL DEFAULT '',
    result             jsonb,
    recommendation     jsonb,
    explanation        jsonb,
    selected_option_id text,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX scenarios_brand_idx ON scenarios (brand_id, created_at DESC);

CREATE TABLE risk_signals (
    id              text PRIMARY KEY,
    brand_id        text NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    source_text     text NOT NULL,
    source_type     text NOT NULL DEFAULT 'other' CHECK (source_type IN ('tariff', 'supplier_news', 'other')),
    quote           text NOT NULL,
    quote_start     integer NOT NULL,
    quote_end       integer NOT NULL,
    target_type     text NOT NULL CHECK (target_type IN ('hts_code', 'supplier', 'sku')),
    target_id       text NOT NULL,
    parameter       text NOT NULL,
    change_type     text NOT NULL CHECK (change_type IN ('set', 'delta', 'multiply')),
    change_value    double precision NOT NULL,
    probability     double precision NOT NULL CHECK (probability BETWEEN 0 AND 1),
    llm_probability double precision,
    effective_date  date,
    status          text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected')),
    edited_by_user  boolean NOT NULL DEFAULT false,
    -- 以下为 agent 层的校验结果
    matched         boolean NOT NULL DEFAULT true,
    affected_skus   text[] NOT NULL DEFAULT '{}',
    value_grounded  boolean NOT NULL DEFAULT true,
    rationale       text NOT NULL DEFAULT '',
    created_at      timestamptz NOT NULL DEFAULT now(),
    -- 服务端硬约束：引用必须是原文子串
    CHECK (quote_start >= 0 AND quote_end > quote_start
           AND substr(source_text, quote_start + 1, quote_end - quote_start) = quote)
);
CREATE INDEX risk_signals_brand_status_idx ON risk_signals (brand_id, status);

CREATE TABLE preset_events (
    id           text PRIMARY KEY,
    brand_id     text NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    name         text NOT NULL,
    description  text NOT NULL,
    signals      jsonb NOT NULL
);

CREATE TABLE alerts (
    id                text PRIMARY KEY,
    brand_id          text NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    event_id          text NOT NULL,
    purchase_order_id text NOT NULL REFERENCES purchase_orders(id),
    extra_cost        double precision NOT NULL DEFAULT 0,
    cash_gap          double precision NOT NULL DEFAULT 0,
    message           text NOT NULL,
    next_step         text NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    acknowledged      boolean NOT NULL DEFAULT false
);
CREATE INDEX alerts_brand_ack_idx ON alerts (brand_id, acknowledged, created_at DESC);

-- 工厂底线只在服务端，persona 整体存 JSONB
CREATE TABLE factory_personas (
    supplier_id  text PRIMARY KEY REFERENCES suppliers(id) ON DELETE CASCADE,
    persona      jsonb NOT NULL
);

CREATE TABLE negotiations (
    id               text PRIMARY KEY,
    brand_id         text NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    supplier_id      text NOT NULL REFERENCES suppliers(id),
    sku_id           text NOT NULL REFERENCES skus(id),
    base_scenario_id text REFERENCES scenarios(id),
    status           text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'agreed', 'walked_away')),
    turns            jsonb NOT NULL DEFAULT '[]',
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE votes (
    id          text PRIMARY KEY,
    demo_point  integer NOT NULL CHECK (demo_point BETWEEN 1 AND 3),
    choice      text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
