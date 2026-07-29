-- ============================================================
-- KEM_DDENKI 統合 PostgreSQL スキーマ
-- ============================================================
-- スキーマ分離:
--   master.*    共通マスタ（社員・現場・仕入先・発注先）
--   bid.*       入札案件管理
--   material.*  材料・発注管理
--   labor.*     作業日報（sagyo-nippou）
--   attend.*    勤怠管理（nippou-kanri）
--   sales.*     営業来訪管理
--   eval.*      人事評価
--   ai.*        AI見積もり用ビュー
-- ============================================================

-- スキーマ作成
CREATE SCHEMA IF NOT EXISTS master;
CREATE SCHEMA IF NOT EXISTS bid;
CREATE SCHEMA IF NOT EXISTS material;
CREATE SCHEMA IF NOT EXISTS labor;
CREATE SCHEMA IF NOT EXISTS attend;
CREATE SCHEMA IF NOT EXISTS sales;
CREATE SCHEMA IF NOT EXISTS eval;
CREATE SCHEMA IF NOT EXISTS ai;

-- ============================================================
-- 共通マスタ (master)
-- ============================================================

CREATE TABLE IF NOT EXISTS master.employees (
    id          SERIAL PRIMARY KEY,
    code        TEXT DEFAULT '',
    name        TEXT NOT NULL,
    kana        TEXT DEFAULT '',
    department  TEXT DEFAULT '',
    position    TEXT DEFAULT '',
    role        TEXT DEFAULT '',        -- 職種（電工/事務/役員等）
    phone       TEXT DEFAULT '',
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    note        TEXT DEFAULT '',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(name)
);

CREATE TABLE IF NOT EXISTS master.sites (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    client      TEXT DEFAULT '',        -- 発注先名
    client_id   INTEGER,                -- master.clients への参照（任意）
    address     TEXT DEFAULT '',
    region      TEXT DEFAULT '',
    category    TEXT DEFAULT '',         -- 工事種別
    scale       TEXT DEFAULT '',
    start_date  DATE,
    end_date    DATE,
    status      TEXT NOT NULL DEFAULT '着工前',
    manager     TEXT DEFAULT '',
    memo        TEXT DEFAULT '',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS master.clients (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    contact     TEXT DEFAULT '',
    phone       TEXT DEFAULT '',
    memo        TEXT DEFAULT '',
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS master.suppliers (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    contact     TEXT DEFAULT '',
    category    TEXT DEFAULT '',
    phone       TEXT DEFAULT '',
    memo        TEXT DEFAULT '',
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 入札案件管理 (bid)
-- ============================================================

CREATE TABLE IF NOT EXISTS bid.projects (
    id          SERIAL PRIMARY KEY,
    site_id     INTEGER REFERENCES master.sites(id),  -- 共通現場への紐付け
    title       TEXT NOT NULL,
    client      TEXT,
    region      TEXT,
    category    TEXT,
    deadline    DATE,
    budget      INTEGER,
    source_url  TEXT,
    status      TEXT NOT NULL DEFAULT '新着',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(title, source_url)
);

CREATE TABLE IF NOT EXISTS bid.costs (
    id              SERIAL PRIMARY KEY,
    project_id      INTEGER NOT NULL UNIQUE REFERENCES bid.projects(id) ON DELETE CASCADE,
    estimate_amount INTEGER,
    actual_cost     INTEGER,
    profit          INTEGER,
    profit_rate     REAL,
    memo            TEXT,
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bid.competitors (
    id                SERIAL PRIMARY KEY,
    project_id        INTEGER NOT NULL REFERENCES bid.projects(id) ON DELETE CASCADE,
    competitor_name   TEXT,
    competitor_amount INTEGER,
    diff_amount       INTEGER,
    source            TEXT,
    memo              TEXT
);

CREATE TABLE IF NOT EXISTS bid.scrape_targets (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    url             TEXT NOT NULL UNIQUE,
    region          TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_scraped_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bid.unit_prices (
    id         SERIAL PRIMARY KEY,
    category   TEXT,
    item_name  TEXT NOT NULL,
    unit       TEXT,
    unit_price INTEGER,
    memo       TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bid.qualifications (
    id                 SERIAL PRIMARY KEY,
    issuer             TEXT NOT NULL,
    category           TEXT,
    grade              TEXT,
    keisin_score       INTEGER,
    total_score        INTEGER,
    vendor_number      TEXT,
    valid_from         DATE,
    valid_until        DATE,
    application_type   TEXT,
    application_method TEXT,
    renewed            BOOLEAN NOT NULL DEFAULT FALSE,
    memo               TEXT,
    imported_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 材料・発注管理 (material)
-- ============================================================

CREATE TABLE IF NOT EXISTS material.item_master (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    spec            TEXT DEFAULT '',
    unit            TEXT NOT NULL DEFAULT '個',
    category        TEXT DEFAULT '',
    subcategory     TEXT DEFAULT '',
    standard_price  INTEGER DEFAULT 0,
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS material.estimate_header (
    id          SERIAL PRIMARY KEY,
    project_id  INTEGER NOT NULL,   -- bid.projects または master.sites への参照
    version     INTEGER NOT NULL DEFAULT 1,
    total_amount INTEGER DEFAULT 0,
    submitted   BOOLEAN NOT NULL DEFAULT FALSE,
    created_by  TEXT DEFAULT '',
    memo        TEXT DEFAULT '',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS material.estimate_line (
    id          SERIAL PRIMARY KEY,
    header_id   INTEGER NOT NULL REFERENCES material.estimate_header(id) ON DELETE CASCADE,
    item_id     INTEGER NOT NULL REFERENCES material.item_master(id),
    quantity    REAL NOT NULL,
    unit_price  INTEGER NOT NULL,
    amount      INTEGER NOT NULL,
    sort_order  INTEGER DEFAULT 0,
    memo        TEXT DEFAULT '',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS material.orders (
    id          SERIAL PRIMARY KEY,
    project_id  INTEGER NOT NULL,
    item_id     INTEGER NOT NULL REFERENCES material.item_master(id),
    supplier_id INTEGER REFERENCES master.suppliers(id),
    quantity    REAL NOT NULL,
    unit_price  INTEGER NOT NULL,
    amount      INTEGER NOT NULL,
    order_date  DATE NOT NULL,
    orderer     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT '発注済',
    memo        TEXT DEFAULT '',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS material.price_history (
    id            SERIAL PRIMARY KEY,
    item_id       INTEGER NOT NULL REFERENCES material.item_master(id),
    supplier_id   INTEGER REFERENCES master.suppliers(id),
    unit_price    INTEGER NOT NULL,
    recorded_date DATE NOT NULL,
    source        TEXT DEFAULT '',
    memo          TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS material.order_cost (
    id          SERIAL PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES material.orders(id) ON DELETE CASCADE,
    cost_type   TEXT NOT NULL,
    amount      INTEGER NOT NULL,
    memo        TEXT DEFAULT '',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS material.receipt (
    id          SERIAL PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES material.orders(id) ON DELETE CASCADE,
    file_path   TEXT NOT NULL,
    file_name   TEXT NOT NULL,
    uploaded_by TEXT DEFAULT '',
    uploaded_at TIMESTAMP NOT NULL DEFAULT NOW(),
    memo        TEXT DEFAULT ''
);

-- ============================================================
-- 作業日報 (labor) — sagyo-nippou
-- ============================================================

CREATE TABLE IF NOT EXISTS labor.reports (
    id                  SERIAL PRIMARY KEY,
    report_date         DATE NOT NULL,
    reporter_name       TEXT,
    site_id             INTEGER REFERENCES master.sites(id),
    client              TEXT DEFAULT '',
    work_content        TEXT DEFAULT '',
    own_car             BOOLEAN NOT NULL DEFAULT FALSE,
    own_train           BOOLEAN NOT NULL DEFAULT FALSE,
    own_car_count       INTEGER NOT NULL DEFAULT 0,
    own_transport_cost  INTEGER NOT NULL DEFAULT 0,
    manager             TEXT DEFAULT '',
    status              TEXT NOT NULL DEFAULT '提出済',
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS labor.report_workers (
    id           SERIAL PRIMARY KEY,
    report_id    INTEGER NOT NULL REFERENCES labor.reports(id) ON DELETE CASCADE,
    worker_id    INTEGER REFERENCES master.employees(id),
    worker_name  TEXT NOT NULL,
    start_time   TEXT,
    end_time     TEXT,
    overtime_h   REAL NOT NULL DEFAULT 0,
    lodging      BOOLEAN NOT NULL DEFAULT FALSE,
    work_hours   REAL NOT NULL DEFAULT 0,
    sort_order   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS labor.report_subcontractors (
    id               SERIAL PRIMARY KEY,
    report_id        INTEGER NOT NULL REFERENCES labor.reports(id) ON DELETE CASCADE,
    company_name     TEXT NOT NULL,
    worker_name      TEXT DEFAULT '',
    headcount        INTEGER NOT NULL DEFAULT 0,
    start_time       TEXT,
    end_time         TEXT,
    work_content     TEXT DEFAULT '',
    transport_car    BOOLEAN NOT NULL DEFAULT FALSE,
    transport_share  BOOLEAN NOT NULL DEFAULT FALSE,
    transport_train  BOOLEAN NOT NULL DEFAULT FALSE,
    car_count        INTEGER NOT NULL DEFAULT 0,
    transport_cost   INTEGER NOT NULL DEFAULT 0,
    approved         BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS labor.office_reports (
    id              SERIAL PRIMARY KEY,
    report_date     DATE NOT NULL,
    worker_id       INTEGER REFERENCES master.employees(id),
    worker_name     TEXT NOT NULL,
    start_time      TEXT,
    end_time        TEXT,
    work_hours      REAL NOT NULL DEFAULT 0,
    work_content    TEXT DEFAULT '',
    report_content  TEXT DEFAULT '',
    next_content    TEXT DEFAULT '',
    role            TEXT NOT NULL DEFAULT '事務員',
    status          TEXT NOT NULL DEFAULT '提出済',
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 勤怠管理 (attend) — nippou-kanri
-- ============================================================

CREATE TABLE IF NOT EXISTS attend.reports (
    id            SERIAL PRIMARY KEY,
    report_date   DATE NOT NULL,
    site_name     TEXT DEFAULT '',
    work_content  TEXT DEFAULT '',
    note          TEXT DEFAULT '',
    status        TEXT NOT NULL DEFAULT '未確認',
    source_text   TEXT DEFAULT '',
    source_key    TEXT DEFAULT '',
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS attend.entries (
    id               SERIAL PRIMARY KEY,
    report_id        INTEGER NOT NULL REFERENCES attend.reports(id) ON DELETE CASCADE,
    employee_id      INTEGER REFERENCES master.employees(id) ON DELETE SET NULL,
    employee_name    TEXT NOT NULL DEFAULT '',
    start_time       TEXT DEFAULT '',
    end_time         TEXT DEFAULT '',
    break_minutes    INTEGER DEFAULT 0,
    early_minutes    INTEGER NOT NULL DEFAULT 0,
    normal_minutes   INTEGER NOT NULL DEFAULT 0,
    overtime_minutes INTEGER NOT NULL DEFAULT 0,
    total_minutes    INTEGER NOT NULL DEFAULT 0,
    note             TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS attend.settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ============================================================
-- 営業来訪管理 (sales) — eigyo-kanri
-- ============================================================

CREATE TABLE IF NOT EXISTS sales.visits (
    id                SERIAL PRIMARY KEY,
    industry          TEXT NOT NULL DEFAULT 'その他',
    company_name      TEXT NOT NULL DEFAULT '',
    rep_name          TEXT NOT NULL DEFAULT '',
    business_overview TEXT NOT NULL DEFAULT '',
    sales_content     TEXT NOT NULL DEFAULT '',
    phone             TEXT NOT NULL DEFAULT '',
    email             TEXT NOT NULL DEFAULT '',
    website           TEXT NOT NULL DEFAULT '',
    address           TEXT NOT NULL DEFAULT '',
    visit_date        DATE,
    received_date     DATE,
    source_file       TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT '下書き',
    memo              TEXT NOT NULL DEFAULT '',
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 人事評価 (eval)
-- ============================================================

CREATE TABLE IF NOT EXISTS eval.evaluations (
    id           SERIAL PRIMARY KEY,
    employee     TEXT NOT NULL,
    role         TEXT NOT NULL,
    period       TEXT NOT NULL,
    evaluator    TEXT,
    choice_field TEXT,
    max_total    INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS eval.eval_scores (
    id            SERIAL PRIMARY KEY,
    evaluation_id INTEGER NOT NULL REFERENCES eval.evaluations(id) ON DELETE CASCADE,
    item_num      INTEGER NOT NULL,
    item_name     TEXT NOT NULL,
    score         INTEGER NOT NULL DEFAULT 0,
    comment       TEXT
);

CREATE TABLE IF NOT EXISTS eval.eval_items (
    id           SERIAL PRIMARY KEY,
    section      TEXT NOT NULL,
    num          INTEGER NOT NULL,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    max_score    INTEGER NOT NULL DEFAULT 10,
    choice_group TEXT,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    anchor_5     TEXT NOT NULL DEFAULT '',
    anchor_3     TEXT NOT NULL DEFAULT '',
    anchor_1     TEXT NOT NULL DEFAULT '',
    free_text    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS eval.survey_questions (
    id         SERIAL PRIMARY KEY,
    item_id    INTEGER NOT NULL REFERENCES eval.eval_items(id) ON DELETE CASCADE,
    qnum       TEXT NOT NULL DEFAULT '',
    text       TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS eval.eval_answers (
    id            SERIAL PRIMARY KEY,
    evaluation_id INTEGER NOT NULL REFERENCES eval.evaluations(id) ON DELETE CASCADE,
    item_id       INTEGER,
    item_name     TEXT NOT NULL DEFAULT '',
    qnum          TEXT NOT NULL DEFAULT '',
    question_text TEXT NOT NULL DEFAULT '',
    answer        INTEGER
);

CREATE TABLE IF NOT EXISTS eval.eval_overall (
    id            SERIAL PRIMARY KEY,
    evaluation_id INTEGER NOT NULL REFERENCES eval.evaluations(id) ON DELETE CASCADE,
    qnum          TEXT NOT NULL DEFAULT '',
    question_text TEXT NOT NULL DEFAULT '',
    answer_text   TEXT NOT NULL DEFAULT ''
);

-- ============================================================
-- 工期管理 (schedule) — 現場ごとの工程・マイルストーン
-- ============================================================
CREATE SCHEMA IF NOT EXISTS schedule;

-- 工程（1現場に複数の工程フェーズ）
CREATE TABLE IF NOT EXISTS schedule.phases (
    id          SERIAL PRIMARY KEY,
    site_id     INTEGER NOT NULL REFERENCES master.sites(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,              -- 工程名（例: 仮設, 幹線, 照明, 検査）
    start_date  DATE,
    end_date    DATE,
    progress    INTEGER NOT NULL DEFAULT 0, -- 進捗率 0-100
    sort_order  INTEGER NOT NULL DEFAULT 0,
    color       TEXT DEFAULT '',            -- ガントチャート色 (例: #3b82f6)
    memo        TEXT DEFAULT '',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- マイルストーン（検査日・引き渡し日など重要日）
CREATE TABLE IF NOT EXISTS schedule.milestones (
    id          SERIAL PRIMARY KEY,
    site_id     INTEGER NOT NULL REFERENCES master.sites(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,              -- 例: 中間検査, 完了検査, 引き渡し
    target_date DATE NOT NULL,
    completed   BOOLEAN NOT NULL DEFAULT FALSE,
    memo        TEXT DEFAULT '',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 配置管理（作業員の現場配置）
CREATE TABLE IF NOT EXISTS schedule.assignments (
    id          SERIAL PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES master.employees(id) ON DELETE CASCADE,
    employee_name TEXT NOT NULL,
    site_id     INTEGER NOT NULL REFERENCES master.sites(id) ON DELETE CASCADE,
    site_name   TEXT NOT NULL DEFAULT '',
    start_date  DATE NOT NULL,
    end_date    DATE,              -- NULL = 無期限（次の配置まで有効）
    memo        TEXT DEFAULT '',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_schedule_phases_site ON schedule.phases(site_id);
CREATE INDEX IF NOT EXISTS idx_schedule_milestones_site ON schedule.milestones(site_id);
CREATE INDEX IF NOT EXISTS idx_assignments_emp ON schedule.assignments(employee_id);
CREATE INDEX IF NOT EXISTS idx_assignments_site ON schedule.assignments(site_id);
CREATE INDEX IF NOT EXISTS idx_assignments_dates ON schedule.assignments(start_date, end_date);

-- ============================================================
-- インデックス
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_labor_reports_date ON labor.reports(report_date);
CREATE INDEX IF NOT EXISTS idx_labor_reports_site ON labor.reports(site_id);
CREATE INDEX IF NOT EXISTS idx_labor_rworkers_report ON labor.report_workers(report_id);
CREATE INDEX IF NOT EXISTS idx_labor_rsubs_report ON labor.report_subcontractors(report_id);
CREATE INDEX IF NOT EXISTS idx_labor_office_date ON labor.office_reports(report_date);
CREATE INDEX IF NOT EXISTS idx_attend_reports_date ON attend.reports(report_date);
CREATE INDEX IF NOT EXISTS idx_attend_entries_report ON attend.entries(report_id);
CREATE INDEX IF NOT EXISTS idx_attend_entries_emp ON attend.entries(employee_id);
CREATE INDEX IF NOT EXISTS idx_attend_reports_source ON attend.reports(source_key);

-- ============================================================
-- AI 見積もりビュー (Step 4)
-- ============================================================

CREATE OR REPLACE VIEW ai.project_cost_summary AS
SELECT
    bp.id AS project_id,
    bp.title,
    bp.category,
    bp.region,
    bp.budget,
    bp.status,
    bp.deadline,
    bc.estimate_amount,
    bc.actual_cost,
    bc.profit,
    bc.profit_rate,
    -- 材料費合計
    (SELECT COALESCE(SUM(mo.amount), 0)
     FROM material.orders mo
     WHERE mo.project_id = bp.id) AS material_cost,
    -- 材料付帯コスト合計
    (SELECT COALESCE(SUM(moc.amount), 0)
     FROM material.order_cost moc
     JOIN material.orders mo2 ON mo2.id = moc.order_id
     WHERE mo2.project_id = bp.id) AS material_overhead,
    -- 作業日報からの人工数 (man-hours)
    (SELECT COALESCE(SUM(lrw.work_hours), 0)
     FROM labor.report_workers lrw
     JOIN labor.reports lr ON lr.id = lrw.report_id
     WHERE lr.site_id = bp.site_id
       AND bp.site_id IS NOT NULL) AS total_man_hours,
    -- 作業日報からの残業時間
    (SELECT COALESCE(SUM(lrw.overtime_h), 0)
     FROM labor.report_workers lrw
     JOIN labor.reports lr ON lr.id = lrw.report_id
     WHERE lr.site_id = bp.site_id
       AND bp.site_id IS NOT NULL) AS total_overtime_hours,
    -- 作業日数
    (SELECT COUNT(DISTINCT lr.report_date)
     FROM labor.reports lr
     WHERE lr.site_id = bp.site_id
       AND bp.site_id IS NOT NULL) AS work_days,
    -- 最安競合額
    (SELECT MIN(bcomp.competitor_amount)
     FROM bid.competitors bcomp
     WHERE bcomp.project_id = bp.id) AS lowest_competitor_amount,
    bp.created_at
FROM bid.projects bp
LEFT JOIN bid.costs bc ON bc.project_id = bp.id;

-- 品目別コスト分析ビュー
CREATE OR REPLACE VIEW ai.item_cost_analysis AS
SELECT
    im.id AS item_id,
    im.name AS item_name,
    im.spec,
    im.unit,
    im.category,
    COUNT(mo.id) AS total_orders,
    AVG(mo.unit_price) AS avg_price,
    MIN(mo.unit_price) AS min_price,
    MAX(mo.unit_price) AS max_price,
    -- 直近単価
    (SELECT mo2.unit_price FROM material.orders mo2
     WHERE mo2.item_id = im.id ORDER BY mo2.order_date DESC LIMIT 1) AS latest_price,
    -- 最安仕入先
    (SELECT s.name FROM material.orders mo3
     JOIN master.suppliers s ON s.id = mo3.supplier_id
     WHERE mo3.item_id = im.id AND mo3.supplier_id IS NOT NULL
     GROUP BY mo3.supplier_id, s.name
     ORDER BY AVG(mo3.unit_price) ASC LIMIT 1) AS best_supplier,
    -- 平均輸送費
    COALESCE((SELECT AVG(moc.amount) FROM material.order_cost moc
     JOIN material.orders mo4 ON mo4.id = moc.order_id
     WHERE mo4.item_id = im.id AND moc.cost_type = '輸送費'), 0) AS avg_transport
FROM material.item_master im
JOIN material.orders mo ON mo.item_id = im.id
GROUP BY im.id, im.name, im.spec, im.unit, im.category
HAVING COUNT(mo.id) >= 1;
