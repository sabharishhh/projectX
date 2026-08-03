use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};
use sha2::{Digest, Sha256};

/// A single directed relationship between two memory units, stored
/// content-addressable exactly like MemoryUnit — hash of its own
/// content, referenced by commits alongside unit hashes.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Edge {
    pub from_hash: String,
    pub to_hash: String,
    pub reason: String,       // short LLM-written phrase, e.g. "same project"
    pub created_at: DateTime<Utc>,
}

impl Edge {
    pub fn new(from_hash: String, to_hash: String, reason: String) -> Self {
        Self { from_hash, to_hash, reason, created_at: Utc::now() }
    }

    /// Content hash — same pattern as MemoryUnit::hash(). Deliberately
    /// excludes created_at so identical (from, to, reason) edges
    /// captured twice dedupe naturally instead of piling up.
    pub fn hash(&self) -> String {
        let mut hasher = Sha256::new();
        hasher.update(self.from_hash.as_bytes());
        hasher.update(self.to_hash.as_bytes());
        hasher.update(self.reason.as_bytes());
        hasher.finalize().iter().map(|b| format!("{:02x}", b)).collect()
    }
}

/// Read-side helper: given a set of top-ranked unit hashes, find every
/// edge touching them and return the connected hashes not already in
/// that set. One hop only — deliberately not recursive, to avoid
/// unbounded graph walks eating the token budget on a densely linked
/// store.
pub fn one_hop_neighbors(
    seed_hashes: &[String],
    all_edges: &[Edge],
) -> Vec<(String, String)> {
    // Returns (neighbor_hash, reason) pairs, so retrieval can surface
    // *why* each neighbor got pulled in — needed for the trace UI.
    let seed_set: std::collections::HashSet<&str> =
        seed_hashes.iter().map(|s| s.as_str()).collect();

    let mut neighbors = Vec::new();
    for edge in all_edges {
        if seed_set.contains(edge.from_hash.as_str()) && !seed_set.contains(edge.to_hash.as_str()) {
            neighbors.push((edge.to_hash.clone(), edge.reason.clone()));
        } else if seed_set.contains(edge.to_hash.as_str()) && !seed_set.contains(edge.from_hash.as_str()) {
            neighbors.push((edge.from_hash.clone(), edge.reason.clone()));
        }
    }
    neighbors
}