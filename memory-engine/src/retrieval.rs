use std::collections::HashMap;

use rust_stemmers::{Algorithm, Stemmer};

use crate::unit::{MemoryUnit, UnitType};

pub struct ScoredUnit {
    pub hash: String,
    pub unit: MemoryUnit,
    pub score: f64,
}

const K1: f64 = 1.2;
const B: f64 = 0.75;
// A unit must clear this before it's eligible at all — keeps recency or a
// weakly-common word from single-handedly qualifying an irrelevant fact.
const MIN_BM25_SCORE: f64 = 0.05;

fn tokenize(text: &str) -> Vec<String> {
    let stemmer = Stemmer::create(Algorithm::English);
    text.to_lowercase()
        .split(|c: char| !c.is_alphanumeric())
        .filter(|w| w.len() > 1)
        .map(|w| stemmer.stem(w).to_string())
        .collect()
}

/// BM25 relevance of `query` against each unit's content, using the other
/// candidate units as the corpus for IDF statistics. Self-normalizing: a
/// term common across most stored facts (like "the") is automatically
/// pushed toward zero or negative weight — no stopword list required.
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
    let avgdl: f64 =
        doc_tokens.iter().map(|(_, t)| t.len() as f64).sum::<f64>() / n;

    // document frequency per query term, across this candidate set
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
                    // classic Robertson-Sparck Jones IDF — deliberately allows
                    // near-zero or negative weight for terms common across
                    // the corpus, rather than clamping them to a floor
                    let idf = ((n - n_t + 0.5) / (n_t + 0.5)).ln();
                    let denom = tf + K1 * (1.0 - B + B * dl / avgdl);
                    idf * (tf * (K1 + 1.0)) / denom
                })
                .sum();
            (hash.clone(), score)
        })
        .collect()
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

/// Ranks units by relevance to `query`. Highest score first. Units with no
/// genuine textual relevance are excluded, regardless of how recent they are.
pub fn score(
    query: &str,
    units: &[(String, MemoryUnit)],
    boost: &[UnitType],
) -> Vec<ScoredUnit> {
    let bm25 = bm25_scores(query, units);

    let mut scored: Vec<ScoredUnit> = units
        .iter()
        .filter_map(|(hash, unit)| {
            let relevance = *bm25.get(hash).unwrap_or(&0.0);
            let priority = type_priority(unit.unit_type, query);

            // A unit qualifies either through genuine content overlap, or
            // through an intent match (the query's phrasing signals this
            // unit's *type* is what's being asked about, even with zero
            // shared words — e.g. "what am I working on?" vs a project
            // fact phrased entirely differently).
            let intent_match = priority > 1.0;
            if relevance < MIN_BM25_SCORE && !intent_match {
                return None;
            }

            let recency = recency_score(unit.created_at);
            let skill_boost = if boost.contains(&unit.unit_type) { 1.4 } else { 1.0 };
            Some(ScoredUnit {
                hash: hash.clone(),
                unit: unit.clone(),
                score: (relevance.max(0.0) + recency) * priority * skill_boost,
            })
        })
        .collect();

    scored.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());
    scored
}