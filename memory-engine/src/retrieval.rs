use std::collections::HashMap;

use rust_stemmers::{Algorithm, Stemmer};

use crate::unit::{MemoryUnit, UnitType};

pub struct ScoredUnit {
    pub hash: String,
    pub unit: MemoryUnit,
    pub score: f64,
    pub bm25_score: f64,
    pub dense_score: f64,
}

const K1: f64 = 1.2;
const B: f64 = 0.75;
const MIN_BM25_SCORE: f64 = 0.05;
// Cosine floor for bge-base-en. Starting guess, not measured — BGE
// embeddings of unrelated sentences typically sit ~0.2-0.3 due to
// anisotropy, so this needs the same empirical tuning MIN_BM25_SCORE got.
const MIN_DENSE_SCORE: f64 = 0.35;

fn tokenize(text: &str) -> Vec<String> {
    let stemmer = Stemmer::create(Algorithm::English);
    text.to_lowercase()
        .split(|c: char| !c.is_alphanumeric())
        .filter(|w| w.len() > 1)
        .map(|w| stemmer.stem(w).to_string())
        .collect()
}

fn bm25_scores(query: &str, units: &[(String, MemoryUnit)]) -> HashMap<String, f64> {
    let query_terms = tokenize(query);
    if query_terms.is_empty() || units.is_empty() {
        return HashMap::new();
    }

    let doc_tokens: Vec<(String, Vec<String>)> = units
        .iter()
        .map(|(hash, unit)| (hash.clone(), tokenize(&unit.content)))
        .collect();

    let n = doc_tokens.len() as f64;
    let avgdl: f64 = doc_tokens.iter().map(|(_, t)| t.len() as f64).sum::<f64>() / n;

    let df: HashMap<&str, f64> = query_terms
        .iter()
        .map(|term| {
            let count = doc_tokens
                .iter()
                .filter(|(_, tokens)| tokens.contains(term))
                .count() as f64;
            (term.as_str(), count)
        })
        .collect();

    doc_tokens
        .iter()
        .map(|(hash, tokens)| {
            let dl = tokens.len() as f64;
            let score: f64 = query_terms
                .iter()
                .map(|term| {
                    let tf = tokens.iter().filter(|t| *t == term).count() as f64;
                    if tf == 0.0 {
                        return 0.0;
                    }
                    let n_t = *df.get(term.as_str()).unwrap_or(&0.0);
                    let idf = ((n - n_t + 0.5) / (n_t + 0.5)).ln();
                    let denom = tf + K1 * (1.0 - B + B * dl / avgdl);
                    idf * (tf * (K1 + 1.0)) / denom
                })
                .sum();
            (hash.clone(), score)
        })
        .collect()
}

/// Cosine similarity of `query_embedding` against each unit's cached
/// embedding. A unit missing an embedding scores 0 here and falls back
/// entirely on BM25 — never panics on incomplete backfill.
fn dense_scores(
    query_embedding: &[f32],
    units: &[(String, MemoryUnit)],
    embeddings: &HashMap<String, Vec<f32>>,
) -> HashMap<String, f64> {
    units
        .iter()
        .map(|(hash, _)| {
            let sim = embeddings
                .get(hash)
                .map(|e| crate::embedding::cosine_sim(query_embedding, e) as f64)
                .unwrap_or(0.0);
            (hash.clone(), sim)
        })
        .collect()
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

/// Ranks units by relevance to `query`. A unit qualifies if BM25 clears its
/// floor, OR dense similarity clears its floor, OR the query's phrasing
/// signals intent for this unit's type — any one is sufficient, since each
/// signal has a blind spot the others cover.
pub fn score(
    query: &str,
    query_embedding: &[f32],
    units: &[(String, MemoryUnit)],
    embeddings: &HashMap<String, Vec<f32>>,
    boost: &[UnitType],
) -> Vec<ScoredUnit> {
    let bm25 = bm25_scores(query, units);
    let dense = dense_scores(query_embedding, units, embeddings);

    let mut scored: Vec<ScoredUnit> = units
        .iter()
        .filter_map(|(hash, unit)| {
            let bm25_relevance = *bm25.get(hash).unwrap_or(&0.0);
            let dense_relevance = *dense.get(hash).unwrap_or(&0.0);
            let priority = type_priority(unit.unit_type, query);

            let intent_match = priority > 1.0;
            let qualifies = bm25_relevance >= MIN_BM25_SCORE
                || dense_relevance >= MIN_DENSE_SCORE
                || intent_match;
            if !qualifies {
                return None;
            }

            let recency = recency_score(unit.created_at);
            let skill_boost = if boost.contains(&unit.unit_type) { 1.4 } else { 1.0 };

            // Dense weighted 2x as the validated signal; BM25 stays in as
            // a cheap exact-match booster it's genuinely good at.
            let blended = (dense_relevance.max(0.0) * 2.0 + bm25_relevance.max(0.0) + recency)
                * priority
                * skill_boost;

            Some(ScoredUnit {
                hash: hash.clone(),
                unit: unit.clone(),
                score: blended,
                bm25_score: bm25_relevance,
                dense_score: dense_relevance,
            })
        })
        .collect();

    scored.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());
    scored
}