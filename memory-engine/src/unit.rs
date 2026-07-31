use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// What kind of fact this is. Drives retrieval weighting later.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum UnitType {
    Identity,
    Preference,
    Project,
    Decision,
    Relationship,
    Commitment,
    Correction,
}

/// Did the user say this outright, or did we infer it?
/// Inferred units are weighted lower and surfaced tentatively.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Provenance {
    Stated,
    Inferred,
}

/// Lifecycle state for a Commitment unit specifically — None/unused for
/// every other unit_type. A commitment isn't fire-and-forget: it needs to
/// be markable as resolved or abandoned, or it nags forever. Status
/// changes go through the store the same way any other content update
/// does — no new mutation mechanism, just a normal field update.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum CommitmentStatus {
    Open,
    Done,
    Cancelled,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MemoryUnit {
    pub content: String,
    pub unit_type: UnitType,
    pub provenance: Provenance,
    /// Which conversation produced this.
    pub source: String,
    pub created_at: DateTime<Utc>,
    /// Commitment-only fields — None for every other unit_type. Kept as
    /// plain Options on MemoryUnit rather than a separate struct so the
    /// existing store/commit/retrieval machinery needs no new code path
    /// to carry them; they just ride along as extra, usually-empty data.
    #[serde(default)]
    pub deadline: Option<DateTime<Utc>>,
    #[serde(default)]
    pub commitment_status: Option<CommitmentStatus>,
}

impl MemoryUnit {
    pub fn new(
        content: impl Into<String>,
        unit_type: UnitType,
        provenance: Provenance,
        source: impl Into<String>,
    ) -> Self {
        Self {
            content: content.into(),
            unit_type,
            provenance,
            source: source.into(),
            created_at: Utc::now(),
            deadline: None,
            commitment_status: None,
        }
    }

    /// Constructs a commitment unit specifically, with its lifecycle
    /// fields set from the start — the ordinary `new()` always leaves
    /// them None, so a commitment needs this instead, not a follow-up
    /// mutation.
    pub fn new_commitment(
        content: impl Into<String>,
        provenance: Provenance,
        source: impl Into<String>,
        deadline: Option<DateTime<Utc>>,
    ) -> Self {
        Self {
            content: content.into(),
            unit_type: UnitType::Commitment,
            provenance,
            source: source.into(),
            created_at: Utc::now(),
            deadline,
            commitment_status: Some(CommitmentStatus::Open),
        }
    }
}