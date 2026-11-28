/** Physical SQLite schema shared with app/v2/models.py (B1.1). */

export const SCHEMA_SQL = `
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS v2_notes (
  id VARCHAR(64) NOT NULL PRIMARY KEY,
  title VARCHAR(120) NOT NULL,
  content_html TEXT NOT NULL,
  content_text TEXT NOT NULL,
  category VARCHAR(30),
  is_favorite BOOLEAN NOT NULL,
  favorited_at VARCHAR(40),
  is_trashed BOOLEAN NOT NULL,
  trashed_at VARCHAR(40),
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL,
  revision INTEGER NOT NULL,
  extra_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS v2_tags (
  id VARCHAR(64) NOT NULL PRIMARY KEY,
  name VARCHAR(32) NOT NULL UNIQUE,
  color VARCHAR(7) NOT NULL,
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL
);

CREATE TABLE IF NOT EXISTS v2_note_tags (
  note_id VARCHAR(64) NOT NULL,
  tag_id VARCHAR(64) NOT NULL,
  PRIMARY KEY (note_id, tag_id),
  FOREIGN KEY (note_id) REFERENCES v2_notes(id) ON DELETE CASCADE,
  FOREIGN KEY (tag_id) REFERENCES v2_tags(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS v2_attachments (
  id VARCHAR(64) NOT NULL PRIMARY KEY,
  original_name VARCHAR(512) NOT NULL,
  mime VARCHAR(255) NOT NULL,
  size INTEGER NOT NULL,
  sha256 VARCHAR(64) NOT NULL,
  kind VARCHAR(16) NOT NULL,
  stored_name VARCHAR(255) NOT NULL,
  created_at VARCHAR(40) NOT NULL
);

CREATE TABLE IF NOT EXISTS v2_note_attachments (
  note_id VARCHAR(64) NOT NULL,
  attachment_id VARCHAR(64) NOT NULL,
  PRIMARY KEY (note_id, attachment_id),
  FOREIGN KEY (note_id) REFERENCES v2_notes(id) ON DELETE CASCADE,
  FOREIGN KEY (attachment_id) REFERENCES v2_attachments(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS v2_settings (
  key VARCHAR(64) NOT NULL PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at VARCHAR(40) NOT NULL
);

CREATE TABLE IF NOT EXISTS v2_ai_providers (
  id VARCHAR(64) NOT NULL PRIMARY KEY,
  kind VARCHAR(16) NOT NULL,
  label VARCHAR(64) NOT NULL,
  base_url VARCHAR(2048) NOT NULL,
  model VARCHAR(200) NOT NULL,
  key_ref VARCHAR(255),
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL,
  extra_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS v2_conversations (
  id VARCHAR(64) NOT NULL PRIMARY KEY,
  title VARCHAR(200) NOT NULL,
  provider_id VARCHAR(64),
  model VARCHAR(200) NOT NULL DEFAULT '',
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL,
  archived_at VARCHAR(40),
  revision INTEGER NOT NULL DEFAULT 1,
  extra_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS v2_messages (
  id VARCHAR(64) NOT NULL PRIMARY KEY,
  conversation_id VARCHAR(64) NOT NULL,
  role VARCHAR(16) NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  status VARCHAR(16) NOT NULL DEFAULT 'complete',
  sequence INTEGER NOT NULL DEFAULT 1,
  client_id VARCHAR(64),
  error_code VARCHAR(64),
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  FOREIGN KEY (conversation_id) REFERENCES v2_conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_v2_messages_conversation
  ON v2_messages(conversation_id, sequence);
CREATE INDEX IF NOT EXISTS idx_v2_messages_client
  ON v2_messages(conversation_id, client_id);

CREATE TABLE IF NOT EXISTS v2_schema_migrations (
  version INTEGER NOT NULL PRIMARY KEY,
  applied_at VARCHAR(40) NOT NULL,
  checksum VARCHAR(64) NOT NULL
);

CREATE TABLE IF NOT EXISTS v2_import_meta (
  key VARCHAR(64) NOT NULL PRIMARY KEY,
  value TEXT NOT NULL
);
`;