-- D1 schema (SQLite dialect). Apply: wrangler d1 execute shadowbox --file schema.sql
CREATE TABLE IF NOT EXISTS models (
  id TEXT PRIMARY KEY,
  body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS simulations (
  id TEXT PRIMARY KEY,
  model_id TEXT NOT NULL REFERENCES models(id),
  scenario TEXT NOT NULL,
  seed INTEGER NOT NULL,
  status TEXT NOT NULL,
  report TEXT NOT NULL
);
