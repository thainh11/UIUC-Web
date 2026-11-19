CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS topics (
  id       TEXT PRIMARY KEY,          -- OpenAlex topic id, e.g. T11265
  name     TEXT NOT NULL,
  subfield TEXT,
  field    TEXT,
  domain   TEXT
);

CREATE TABLE IF NOT EXISTS papers (
  id               TEXT PRIMARY KEY,  -- OpenAlex work id, e.g. W4417422257
  doi              TEXT,
  title            TEXT NOT NULL,
  abstract         TEXT NOT NULL,
  publication_date DATE NOT NULL,
  cited_by_count   INT  NOT NULL,
  is_oa            BOOLEAN NOT NULL,
  oa_status        TEXT,
  type             TEXT NOT NULL,
  venue            TEXT,
  keywords         TEXT[] NOT NULL DEFAULT '{}',
  primary_topic_id TEXT REFERENCES topics(id),
  embedding        VECTOR(1024),       -- filled by build_embeddings.py
  tsv              TSVECTOR GENERATED ALWAYS AS (
                     setweight(to_tsvector('english', title), 'A') ||
                     setweight(to_tsvector('english', abstract), 'B')
                   ) STORED
);
CREATE INDEX IF NOT EXISTS papers_tsv_idx  ON papers USING GIN (tsv);
CREATE INDEX IF NOT EXISTS papers_date_idx ON papers (publication_date DESC);
CREATE INDEX IF NOT EXISTS papers_topic_idx ON papers (primary_topic_id);

CREATE TABLE IF NOT EXISTS paper_topics (
  paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  topic_id TEXT NOT NULL REFERENCES topics(id),
  score    REAL NOT NULL,
  PRIMARY KEY (paper_id, topic_id)
);

CREATE TABLE IF NOT EXISTS authors (
  id   TEXT PRIMARY KEY,              -- OpenAlex author id, e.g. A5159424365
  name TEXT NOT NULL
);

-- id is generated: email is not unique in the source CSV (c-cheng@illinois.edu belongs to two people).
CREATE TABLE IF NOT EXISTS faculty (
  id          SERIAL PRIMARY KEY,
  email       TEXT NOT NULL,
  name        TEXT NOT NULL,
  photo_url   TEXT,
  position    TEXT
);
-- One row per authorship (position = 0-based order in the OpenAlex list, which caps at 100 authors).
-- author_id is NULL when OpenAlex could not resolve the author. faculty_id/match_score are set by
-- link_authors.py: the link lives on the authorship because OpenAlex splits one person across many
-- author ids and some authorships have no id at all.
CREATE TABLE IF NOT EXISTS paper_authors (
  paper_id    TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  position    INT  NOT NULL,
  author_id   TEXT REFERENCES authors(id),
  name        TEXT NOT NULL,
  is_uiuc     BOOLEAN NOT NULL,       -- this authorship lists UIUC (I157725225)
  has_institution BOOLEAN NOT NULL,   -- this authorship lists any institution
  faculty_id  INT REFERENCES faculty(id) ON DELETE SET NULL,
  match_score REAL,                   -- keywords: IDF sum; semantic: percentile among all papers
  match_method TEXT,                  -- 'keywords' | 'name' | 'semantic'
  PRIMARY KEY (paper_id, position)
);
CREATE INDEX IF NOT EXISTS paper_authors_author_idx  ON paper_authors (author_id);
CREATE INDEX IF NOT EXISTS paper_authors_faculty_idx ON paper_authors (faculty_id);

CREATE TABLE IF NOT EXISTS keywords (
  id        SERIAL PRIMARY KEY,
  text      TEXT NOT NULL UNIQUE,     -- lower-cased, trimmed
  embedding VECTOR(1024)               -- filled by build_embeddings.py
);

CREATE TABLE IF NOT EXISTS faculty_keywords (
  faculty_id INT NOT NULL REFERENCES faculty(id) ON DELETE CASCADE,
  keyword_id INT NOT NULL REFERENCES keywords(id),
  PRIMARY KEY (faculty_id, keyword_id)
);
CREATE INDEX IF NOT EXISTS faculty_keywords_kw_idx ON faculty_keywords (keyword_id);

-- One row per chat request (backend/agent/trace.py). Not in load_db.TABLES: traces outlive a data reload.
-- attrs: message_chars, history_turns, context, rounds, tool_calls, cited, error (+ message with TRACE_PAYLOADS=1).
-- spans: [{name, start_ms, ms, ...}] in start order. payload: the messages sent to the model (TRACE_PAYLOADS=1 only).
CREATE TABLE IF NOT EXISTS chat_traces (
  id          TEXT PRIMARY KEY,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  status      TEXT NOT NULL,          -- 'ok' | 'error' | 'aborted' (client left before the answer finished)
  duration_ms INT NOT NULL,
  attrs       JSONB NOT NULL,
  spans       JSONB NOT NULL,
  payload     JSONB
);
CREATE INDEX IF NOT EXISTS chat_traces_created_idx ON chat_traces (created_at DESC);
