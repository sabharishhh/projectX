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
}

/// Did the user say this outright, or did we infer it?
/// Inferred units are weighted lower and surfaced tentatively.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Provenance {
    Stated,
    Inferred,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MemoryUnit {
    pub content: String,
    pub unit_type: UnitType,
    pub provenance: Provenance,
    /// Which conversation produced this.
    pub source: String,
    pub created_at: DateTime<Utc>,
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
        }
    }
}