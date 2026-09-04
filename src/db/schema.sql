-- kb.db decision ledger. Tables are the architecture §7 draft list.
-- season_id is required from the first write (D-74). Do not invent tables.
-- Child tables inherit season through run_id.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS seasons (
    season_id TEXT PRIMARY KEY,
    league_key TEXT,
    team_key TEXT,
    start_date TEXT,
    end_date TEXT,
    final_record TEXT,
    final_placing INTEGER
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id TEXT NOT NULL REFERENCES seasons (season_id),
    ts TEXT NOT NULL,
    decision_type TEXT NOT NULL,
    packet_hash TEXT,
    failure_mode TEXT,
    publish_approved INTEGER NOT NULL DEFAULT 0,
    publish_denied_reason TEXT,
    manual_intervention INTEGER NOT NULL DEFAULT 0,
    absent_personas TEXT
);

CREATE TABLE IF NOT EXISTS briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs (id),
    persona TEXT NOT NULL,
    recommendations TEXT,
    confidence REAL,
    reasoning TEXT,
    dissent TEXT,
    voice_line TEXT,
    model TEXT,
    tokens INTEGER,
    cost REAL
);

CREATE TABLE IF NOT EXISTS considered_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs (id),
    persona TEXT NOT NULL,
    player_key TEXT NOT NULL,
    contemplated_action TEXT NOT NULL,
    projection_primary REAL,
    projection_secondary REAL,
    projection_delta REAL,
    std_dev REAL,
    injury_status TEXT,
    chosen INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs (id),
    final_actions TEXT NOT NULL,
    adopted_from TEXT,
    overruled TEXT,
    override_reason TEXT,
    unanimous_override INTEGER NOT NULL DEFAULT 0,
    rationale TEXT
);

CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs (id),
    what_happened TEXT,
    points_gained INTEGER,
    points_lost INTEGER
);

CREATE TABLE IF NOT EXISTS attributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs (id),
    persona TEXT NOT NULL,
    counterfactual_points INTEGER,
    directional_accuracy INTEGER,
    brier_contribution REAL,
    adopted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs (id),
    payload TEXT,
    response TEXT,
    errors TEXT,
    pending_review INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS deploys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id TEXT NOT NULL REFERENCES seasons (season_id),
    ts TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    description TEXT NOT NULL,
    touches_decision_logic INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS config_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id TEXT NOT NULL REFERENCES seasons (season_id),
    ts TEXT NOT NULL,
    knob TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_season_id ON runs (season_id);
CREATE INDEX IF NOT EXISTS idx_briefs_run_id ON briefs (run_id);
CREATE INDEX IF NOT EXISTS idx_considered_options_run_id ON considered_options (run_id);
CREATE INDEX IF NOT EXISTS idx_decisions_run_id ON decisions (run_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_run_id ON outcomes (run_id);
CREATE INDEX IF NOT EXISTS idx_attributions_run_id ON attributions (run_id);
CREATE INDEX IF NOT EXISTS idx_executions_run_id ON executions (run_id);
CREATE INDEX IF NOT EXISTS idx_deploys_season_id ON deploys (season_id);
CREATE INDEX IF NOT EXISTS idx_config_changes_season_id ON config_changes (season_id);
