use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// What happened to a unit in this commit.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum UnitChange {
    /// A brand-new fact.
    Added { hash: String },
    /// A fact whose value changed. Both versions stay in the store —
    /// `from` is still readable, it's just no longer current.
    Modified { from: String, to: String },
    /// Soft-forget: retired from HEAD, kept in history, recoverable.
    Superseded { hash: String },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Commit {
    /// None for the first commit in a branch's history.
    pub parent: Option<String>,
    pub changes: Vec<UnitChange>,
    /// Which conversation triggered this.
    pub source: String,
    /// Plain-language semantic diff, written for a human:
    /// "career goal changed from 'stay in current role' to 'exploring founder path'"
    pub summary: String,
    pub created_at: DateTime<Utc>,
}

impl Commit {
    pub fn new(
        parent: Option<String>,
        changes: Vec<UnitChange>,
        source: impl Into<String>,
        summary: impl Into<String>,
    ) -> Self {
        Self {
            parent,
            changes,
            source: source.into(),
            summary: summary.into(),
            created_at: Utc::now(),
        }
    }
}