use std::collections::HashMap;

use crate::unit::{MemoryUnit, UnitType};

/// Minimal contract for anything the retriever can rank. MemoryUnit is the
/// only implementer today; conversation turns or documents can implement
/// this later without becoming MemoryUnits or duplicating scoring logic.
pub trait Retrievable {
    fn id(&self) -> &str;
    fn text(&self) -> &str;
}

impl Retrievable for (String, MemoryUnit) {
    fn id(&self) -> &str { &self.0 }
    fn text(&self) -> &str { &self.1.content }
}

pub struct RankedItem<T> {
    pub item: T,
    pub dense_score: f64,
}

/// Source-agnostic dense ranking. Deliberately has no notion of type
/// priority, recency, or boost — those are MemoryUnit-specific concepts,
/// not universal to everything retrievable, and stay in `score()` below.
pub fn rank_by_relevance<T: Retrievable>(
    query_embedding: &[f32],
    items: Vec<T>,
    embeddings: &HashMap<String, Vec<f32>>,
) -> Vec<RankedItem<T>> {
    let mut ranked: Vec<RankedItem<T>> = items
        .into_iter()
        .map(|item| {
            let dense_score = embeddings
                .get(item.id())
                .map(|e| crate::embedding::cosine_sim(query_embedding, e) as f64)
                .unwrap_or(0.0);
            RankedItem { item, dense_score }
        })
        .collect();
    ranked.sort_by(|a, b| b.dense_score.total_cmp(&a.dense_score));
    ranked
}

pub struct ScoredUnit {
    pub hash: String,
    pub unit: MemoryUnit,
    pub score: f64,
    pub dense_score: f64,
}

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

/// MemoryUnit-specific ranking: dense relevance (via rank_by_relevance)
/// blended with BM25 (exact/rare-term matching), recency, type-intent
/// matching, and skill boost. bm25_scores is precomputed by the caller
/// (only MemoryStore can run a tantivy query) — same pattern already
/// used for embeddings, keeping this module free of any tantivy/store
/// dependency.
pub fn score(
    query: &str,
    query_embedding: &[f32],
    units: Vec<(String, MemoryUnit)>,
    embeddings: &HashMap<String, Vec<f32>>,
    bm25_scores: &HashMap<String, f64>,
    boost: &[UnitType],
) -> Vec<ScoredUnit> {
    let ranked = rank_by_relevance(query_embedding, units, embeddings);

    // Normalize BM25 into a 0–1-ish range before blending — raw BM25 is
    // unbounded and on a completely different scale than cosine
    // similarity (0–1), so blending it in unnormalized would let it
    // silently dominate or do nothing depending on the query. Normalizing
    // against this result set's own max score keeps it comparable to the
    // dense signal regardless of absolute magnitude.
    let max_bm25 = bm25_scores.values().cloned().fold(0.0_f64, f64::max);

    let mut scored: Vec<ScoredUnit> = ranked
        .into_iter()
        .map(|r| {
            let (hash, unit) = r.item;
            let priority = type_priority(unit.unit_type, query);
            let recency = recency_score(unit.created_at);
            let skill_boost = if boost.contains(&unit.unit_type) { 1.4 } else { 1.0 };

            let bm25_norm = if max_bm25 > 0.0 {
                bm25_scores.get(&hash).copied().unwrap_or(0.0) / max_bm25
            } else {
                0.0
            };

            // Dense and BM25 are combined additively (not multiplicatively)
            // before the type/recency/skill multipliers apply — either
            // signal alone should be enough to surface a unit; a fact that
            // BM25 strongly matches but dense ranks poorly (an exact name
            // match phrased very differently from the query) shouldn't be
            // suppressed just because one signal missed it.
            let relevance = r.dense_score.max(0.0) + bm25_norm * 0.5;
            let blended = (relevance + recency * 0.2) * priority * skill_boost;

            ScoredUnit { hash, unit, score: blended, dense_score: r.dense_score }
        })
        .collect();

    scored.sort_by(|a, b| b.score.total_cmp(&a.score));
    scored
}