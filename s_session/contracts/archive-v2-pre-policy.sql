-- #1399：6badaa6049 的 v2 writer 建表后，SQLite 实际登记的 DDL。
-- 调用方已核必需表和可选表组；这里只判每个普通对象是否为原声明，不改写待验 SQL。
WITH registered(name, ddl) AS (VALUES
('meta', 'CREATE TABLE meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
)'),
('raw_events', 'CREATE TABLE raw_events (
  identity_key TEXT NOT NULL,
  revision INTEGER NOT NULL,
  input_revision TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  receipt_id TEXT NOT NULL,
  seq INTEGER NOT NULL UNIQUE,
  source_namespace TEXT NOT NULL,
  source_epoch TEXT NOT NULL,
  instrument TEXT NOT NULL,
  event_id TEXT NOT NULL,
  received_at TEXT NOT NULL,
  raw_text TEXT NOT NULL,
  price TEXT NOT NULL,
  ts TEXT NOT NULL,
  volume TEXT NOT NULL,
  source_coord TEXT NOT NULL,
  supersedes_revision INTEGER,
  PRIMARY KEY (identity_key, revision)
)'),
('batches', 'CREATE TABLE batches (
  batch_id TEXT PRIMARY KEY,
  canonical_bytes BLOB NOT NULL,
  byte_len INTEGER NOT NULL
)'),
('objects', 'CREATE TABLE objects (
  object_id TEXT PRIMARY KEY,
  object_revision INTEGER NOT NULL,
  kind TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  branch TEXT NOT NULL,
  dir_ab TEXT NOT NULL,
  dir_bc TEXT NOT NULL,
  window_start INTEGER NOT NULL,
  window_mid INTEGER NOT NULL,
  window_end INTEGER NOT NULL,
  comparisons_json TEXT NOT NULL,
  input_refs_json TEXT NOT NULL,
  source_coords_json TEXT NOT NULL,
  first_known_generation INTEGER NOT NULL,
  first_known_cut TEXT NOT NULL,
  published_generation INTEGER NOT NULL,
  withdrawn_generation INTEGER,
  withdrawal_reason TEXT,
  superseded_by TEXT
)'),
('witnesses', 'CREATE TABLE witnesses (
  witness_id TEXT PRIMARY KEY,
  object_id TEXT NOT NULL,
  slot INTEGER NOT NULL,
  merged_source_index INTEGER NOT NULL,
  merged_high TEXT NOT NULL,
  merged_low TEXT NOT NULL,
  merged_open TEXT NOT NULL,
  merged_close TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  published_generation INTEGER NOT NULL
)'),
('relations', 'CREATE TABLE relations (
  relation_id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  object TEXT NOT NULL,
  published_generation INTEGER NOT NULL
)'),
('observations', 'CREATE TABLE observations (
  observation_id TEXT PRIMARY KEY,
  batch_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  window_start INTEGER,
  window_mid INTEGER,
  window_end INTEGER,
  reason TEXT NOT NULL,
  detail_json TEXT NOT NULL,
  published_generation INTEGER NOT NULL
)'),
('structure_deltas', 'CREATE TABLE structure_deltas (
  generation INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  catalog_revision TEXT NOT NULL,
  base_cut TEXT NOT NULL,
  next_cut TEXT NOT NULL,
  seq_range_json TEXT NOT NULL,
  index_frontier TEXT NOT NULL,
  input_frontier INTEGER NOT NULL,
  catalog_run_status TEXT NOT NULL,
  catalog_evidence_json TEXT NOT NULL,
  delta_json TEXT NOT NULL
)'),
('writer_epoch_history', 'CREATE TABLE writer_epoch_history (
  ordinal INTEGER PRIMARY KEY,
  from_epoch TEXT NOT NULL,
  to_epoch TEXT NOT NULL,
  generation_at_transition TEXT NOT NULL,
  advance_state_at_transition TEXT NOT NULL,
  transitioned_at TEXT NOT NULL
)'),
('catalog', 'CREATE TABLE catalog (
  catalog_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  domain TEXT NOT NULL,
  branches_json TEXT NOT NULL,
  impl_status TEXT NOT NULL,
  proof_status TEXT NOT NULL,
  run_status TEXT NOT NULL,
  evidence_json TEXT NOT NULL
)'),
('s_protocol_meta', 'CREATE TABLE s_protocol_meta (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 protocol_revision TEXT NOT NULL,
 session_generation TEXT NOT NULL,
 clock_plan_hash TEXT NOT NULL,
 clock_plan_json TEXT NOT NULL,
 next_attempt_ordinal INTEGER NOT NULL CHECK(next_attempt_ordinal>=1),
 logical_phase_frontier TEXT NOT NULL
)'),
('s_input_messages', 'CREATE TABLE s_input_messages (
 source_namespace TEXT NOT NULL,
 source_epoch TEXT NOT NULL,
 message_id TEXT NOT NULL,
 payload_hash TEXT NOT NULL,
 canonical_envelope TEXT NOT NULL,
 receipt_id TEXT NOT NULL,
 accepted_seq INTEGER NOT NULL CHECK(accepted_seq>=0),
 status TEXT NOT NULL CHECK(status IN (''AcceptedPending'',''Committed'')),
 first_published_generation INTEGER,
 clock_event_id TEXT NOT NULL UNIQUE,
 attempt_count INTEGER NOT NULL CHECK(attempt_count>=0),
 PRIMARY KEY(source_namespace,source_epoch,message_id)
)'),
('s_clock_events', 'CREATE TABLE s_clock_events (
 clock_event_id TEXT NOT NULL,
 phase TEXT NOT NULL CHECK(phase IN (''accept'',''begin'',''commit'',''recover'')),
 attempt_index INTEGER NOT NULL,
 semantic_ns TEXT NOT NULL,
 message_key TEXT NOT NULL,
 attempt_ordinal INTEGER,
 generation INTEGER NOT NULL CHECK(generation>=0),
 PRIMARY KEY(clock_event_id,phase,attempt_index)
)'),
('s_delivery_policy', 'CREATE TABLE s_delivery_policy (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 session_id TEXT NOT NULL,
 session_generation TEXT NOT NULL,
 policy_revision TEXT NOT NULL,
 retain_generations INTEGER NOT NULL CHECK(retain_generations>=1),
 first_available_generation INTEGER NOT NULL CHECK(first_available_generation>=1),
 head_generation INTEGER NOT NULL CHECK(head_generation>=0)
)'),
('s_delivery_refs', 'CREATE TABLE s_delivery_refs (
 generation INTEGER PRIMARY KEY CHECK(generation>=1),
 FOREIGN KEY(generation) REFERENCES structure_deltas(generation)
)'),
('raw_ohlc', 'CREATE TABLE raw_ohlc (
  identity_key TEXT NOT NULL,
  revision INTEGER NOT NULL,
  schema_revision TEXT NOT NULL,
  open TEXT NOT NULL,
  high TEXT NOT NULL,
  low TEXT NOT NULL,
  close TEXT NOT NULL,
  PRIMARY KEY(identity_key,revision)
)'),
('structure_facts', 'CREATE TABLE structure_facts (
  object_id TEXT PRIMARY KEY,
  object_revision INTEGER NOT NULL,
  kind TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  fact_key TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  input_refs_json TEXT NOT NULL,
  source_coords_json TEXT NOT NULL,
  first_known_generation INTEGER NOT NULL,
  first_known_cut TEXT NOT NULL,
  published_generation INTEGER NOT NULL,
  withdrawn_generation INTEGER,
  withdrawal_reason TEXT,
  superseded_by TEXT
)'),
('s_storage_format', 'CREATE TABLE s_storage_format (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  storage_format TEXT NOT NULL
)'),
('s_evidence_format', 'CREATE TABLE s_evidence_format (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  graph_format TEXT NOT NULL
)'),
('s_evidence_nodes', 'CREATE TABLE s_evidence_nodes (
  node_id BLOB PRIMARY KEY,
  node_kind INTEGER NOT NULL,
  payload BLOB NOT NULL,
  expanded_length INTEGER NOT NULL
)'),
('s_evidence_roots', 'CREATE TABLE s_evidence_roots (
  root_key TEXT PRIMARY KEY,
  node_id BLOB NOT NULL,
  slot_ids BLOB NOT NULL,
  expanded_length INTEGER NOT NULL,
  content_sha256 TEXT NOT NULL
)')
)
SELECT NOT EXISTS (
  SELECT type, name, tbl_name, sql FROM main.sqlite_schema WHERE name NOT GLOB 'sqlite_*'
  EXCEPT
  SELECT 'table', name, name, ddl FROM registered
);
