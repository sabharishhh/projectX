//! Per-branch BM25 full-text index, backed by tantivy. Complements the
//! dense (embedding) scoring in retrieval.rs — dense catches semantic
//! similarity, BM25 catches exact/rare terms (names, technical terms)
//! that a paraphrase-tolerant embedding can under-rank. Persisted to disk
//! per branch, incrementally updated on every commit — not rebuilt from
//! scratch each query, and not held as one shared index across branches,
//! matching how refs/checkpoints are already laid out per-branch.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use tantivy::collector::{TopDocs};
use tantivy::doc;
use tantivy::query::QueryParser;
use tantivy::schema::{Schema, Value, STORED, STRING, TEXT};
use tantivy::{Index, IndexReader, IndexWriter};

use crate::store::StoreError;

impl From<tantivy::TantivyError> for StoreError {
    fn from(e: tantivy::TantivyError) -> Self {
        StoreError::Io(std::io::Error::other(e.to_string()))
    }
}
impl From<tantivy::query::QueryParserError> for StoreError {
    fn from(e: tantivy::query::QueryParserError) -> Self {
        StoreError::Io(std::io::Error::other(e.to_string()))
    }
}

pub struct BranchIndex {
    index: Index,
    writer: Mutex<IndexWriter>,
    reader: IndexReader,
    hash_field: tantivy::schema::Field,
    content_field: tantivy::schema::Field,
}

impl BranchIndex {
    /// Opens an existing on-disk index at `dir`, or creates a fresh one if
    /// none exists yet — same "lazily created on first real use" pattern
    /// refs/checkpoints already follow, nothing pre-provisioned at store
    /// startup.
    pub fn open_or_create(dir: &Path) -> Result<Self, StoreError> {
        std::fs::create_dir_all(dir)?;

        let mut schema_builder = Schema::builder();
        // STRING (not TEXT): the hash is an exact-match key, never
        // tokenized/stemmed — we look documents up by it, never search
        // "into" it the way we search content.
        let hash_field = schema_builder.add_text_field("hash", STRING | STORED);
        let content_field = schema_builder.add_text_field("content", TEXT);
        let schema = schema_builder.build();

        let index = if dir.read_dir().map(|mut d| d.next().is_some()).unwrap_or(false) {
            Index::open_in_dir(dir)?
        } else {
            Index::create_in_dir(dir, schema.clone())?
        };

        // 15MB writer buffer — comfortably enough for personal-scale
        // memory (hundreds to low-thousands of facts per branch), no
        // reason to reach for tantivy's larger production defaults here.
        let writer: IndexWriter = index.writer(15_000_000)?;
        let reader = index.reader()?;

        Ok(Self { index, writer: Mutex::new(writer), reader, hash_field, content_field })
    }

    /// Adds or updates one unit's content in the index. Tantivy has no
    /// native "update" — this deletes any existing doc for the hash first
    /// (a no-op if it's genuinely new), then adds the current version, so
    /// a Modified change (new hash, same logical fact) never leaves a
    /// stale entry for the OLD hash sitting around — callers are
    /// responsible for indexing the new hash; the old one simply stops
    /// being referenced by current state and is left un-searched, same
    /// gap already accepted for purge_object.
    pub fn upsert(&self, hash: &str, content: &str) -> Result<(), StoreError> {
        let mut writer = self.writer.lock().unwrap();
        let term = tantivy::Term::from_field_text(self.hash_field, hash);
        writer.delete_term(term);
        writer.add_document(doc!(
            self.hash_field => hash,
            self.content_field => content,
        ))?;
        writer.commit()?;
        Ok(())
    }

    /// Returns hash -> BM25 score for whatever matched, best-effort: a
    /// query that fails to parse (stray tantivy query syntax in free-text
    /// user input) returns an empty map rather than erroring the whole
    /// retrieval call — BM25 is one signal among several in score(), not
    /// something that should take down a turn if it hiccups.
    pub fn search(&self, query_text: &str, limit: usize) -> HashMap<String, f64> {
        let searcher = self.reader.searcher();
        let parser = QueryParser::for_index(&self.index, vec![self.content_field]);
        let query = match parser.parse_query(query_text) {
            Ok(q) => q,
            Err(_) => return HashMap::new(),
        };
        let top = match searcher.search(&query, &TopDocs::with_limit(limit).order_by_score()) {
            Ok(t) => t,
            Err(_) => return HashMap::new(),
        };

        let mut out = HashMap::new();
        for (score, doc_address) in top {
            if let Ok(retrieved) = searcher.doc::<tantivy::TantivyDocument>(doc_address) {
                if let Some(hash_val) = retrieved.get_first(self.hash_field) {
                    if let Some(hash_str) = hash_val.as_str() {
                        out.insert(hash_str.to_string(), score as f64);
                    }
                }
            }
        }
        out
    }
}

pub struct BM25Store {
    root: PathBuf,
    branches: Mutex<HashMap<String, BranchIndex>>,
}

impl BM25Store {
    pub fn new(store_root: &Path) -> Self {
        Self {
            root: store_root.join("bm25"),
            branches: Mutex::new(HashMap::new()),
        }
    }

    fn branch_dir(&self, branch: &str) -> PathBuf {
        self.root.join(branch)
    }

    /// Runs `f` against the given branch's index, opening/creating it on
    /// first access and caching the handle for subsequent calls — avoids
    /// re-opening a tantivy writer (a genuinely expensive operation) on
    /// every single commit/query.
    fn with_branch<R>(&self, branch: &str, f: impl FnOnce(&BranchIndex) -> R) -> Result<R, StoreError> {
        let mut branches = self.branches.lock().unwrap();
        if !branches.contains_key(branch) {
            let idx = BranchIndex::open_or_create(&self.branch_dir(branch))?;
            branches.insert(branch.to_string(), idx);
        }
        Ok(f(branches.get(branch).unwrap()))
    }

    pub fn upsert(&self, branch: &str, hash: &str, content: &str) -> Result<(), StoreError> {
        self.with_branch(branch, |idx| idx.upsert(hash, content))?
    }

    pub fn search(&self, branch: &str, query: &str, limit: usize) -> Result<HashMap<String, f64>, StoreError> {
        self.with_branch(branch, |idx| idx.search(query, limit))
    }
}