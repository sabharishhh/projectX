use std::collections::HashSet;

use crate::unit::{MemoryUnit, UnitType};

pub struct ScoredUnit {
    pub hash: String,
    pub unit: MemoryUnit,
    pub score: f64,
}

/// Placeholder for real semantic similarity — swap this for an embedding
/// comparison later without touching anything that calls `score()`.
fn keyword_overlap(query: &str, content: &str) -> f64 {
    let q: HashSet<String> = query
        .to_lowercase()
        .split_whitespace()
        .filter(|w| w.len() > 2)
        .map(|s| s.to_string())
        .collect();
    if q.is_empty() {
        return 0.0;
    }
    let c = content.to_lowercase();
    let hits = q.iter().filter(|w| c.contains(w.as_str())).count();
    hits as f64 / q.len() as f64
}

/// 1.0 for something just committed, decaying toward 0 over ~30 days.
fn recency_score(created_at: chrono::DateTime<chrono::Utc>) -> f64 {
    let days = (chrono::Utc::now() - created_at).num_seconds() as f64 / 86400.0;
    (-days / 30.0).exp()
}

fn type_priority(unit_type: UnitType, query: &str) -> f64 {
    let q = query.to_lowercase();
    match unit_type {
        UnitType::Decision if q.contains("decide") || q.contains("decision") => 1.3,
        UnitType::Project if q.contains("working on") || q.contains("project") => 1.3,
        UnitType::Preference => 1.1,
        _ => 1.0,
    }
}

/// Ranks units by relevance to `query`. Highest score first.
pub fn score(query: &str, units: &[(String, MemoryUnit)]) -> Vec<ScoredUnit> {
    let mut scored: Vec<ScoredUnit> = units
        .iter()
        .map(|(hash, unit)| {
            let relevance = keyword_overlap(query, &unit.content);
            let recency = recency_score(unit.created_at);
            let priority = type_priority(unit.unit_type, query);
            ScoredUnit {
                hash: hash.clone(),
                unit: unit.clone(),
                score: (relevance * 2.0 + recency) * priority,
            }
        })
        .collect();

    scored.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());
    scored
}