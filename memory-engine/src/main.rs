use std::sync::Arc;
use memory_engine::embedding::Embedder;

use axum::{
    extract::{Query, State},
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use memory_engine::{valid_branch_name, Commit, MemoryStore, MemoryUnit, Provenance, UnitChange, UnitType};
use memory_engine::reranker::Reranker;
use memory_engine::entity::{Edge, Entity, EntityType, entity_mediated_neighbors};
use serde::{Deserialize, Serialize};
use tower_http::cors::CorsLayer;

struct AppState {
    store: MemoryStore,
    embedder: Embedder,
    reranker: Reranker,
}

const DENSE_POOL_K: usize = 50;
const PINNED_SENTINEL_SCORE: f64 = 1000.0;

fn default_branch() -> String {
    "main".to_string()
}

#[derive(Deserialize)]
struct BranchQuery {
    #[serde(default = "default_branch")]
    branch: String,
}

#[derive(Deserialize)]
struct RememberRequest {
    content: String,
    unit_type: UnitType,
    provenance: Provenance,
    source: String,
    summary: String,
    #[serde(default = "default_branch")]
    branch: String,
    #[serde(default)]
    deadline: Option<chrono::DateTime<chrono::Utc>>,
    #[serde(default)]
    commitment_status: Option<memory_engine::CommitmentStatus>,
}

#[derive(Deserialize)]
struct SupersedeRequest {
    from: String,
    content: String,
    unit_type: UnitType,
    provenance: Provenance,
    source: String,
    summary: String,
    #[serde(default = "default_branch")]
    branch: String,
    #[serde(default)]
    deadline: Option<chrono::DateTime<chrono::Utc>>,
    #[serde(default)]
    commitment_status: Option<memory_engine::CommitmentStatus>,
}

#[derive(Deserialize)]
struct ForgetRequest {
    hash: String,
    source: String,
    summary: String,
    #[serde(default = "default_branch")]
    branch: String,
}

#[derive(Deserialize)]
struct EdgeRequest {
    from: String,
    to: String,
    relation: String,
    reason: String,
}

#[derive(Deserialize)]
struct ResolveEntityRequest {
    name: String,
    entity_type: EntityType,
}

#[derive(Deserialize)]
struct PutEntityRequest {
    name: String,
    entity_type: EntityType,
    #[serde(default)]
    alias: Option<String>,
}

#[derive(Serialize)]
struct EntityView {
    hash: String,
    #[serde(flatten)]
    entity: Entity,
}

#[derive(Serialize)]
struct EdgeView {
    hash: String,
    #[serde(flatten)]
    edge: Edge,
}

#[derive(Serialize)]
struct UnitView {
    hash: String,
    #[serde(flatten)]
    unit: MemoryUnit,
}

#[derive(Serialize)]
struct ChangeView {
    #[serde(flatten)]
    change: UnitChange,
    unit_type: Option<UnitType>,
}

#[derive(Serialize)]
struct CommitView {
    hash: String,
    parent: Option<String>,
    changes: Vec<ChangeView>,
    source: String,
    summary: String,
    created_at: chrono::DateTime<chrono::Utc>,
}

#[derive(Deserialize)]
struct MergePreviewQuery {
    from: String,
    into: String,
}

#[derive(Serialize)]
struct MergePreview {
    incoming: Vec<UnitView>,  // live on source, absent from target
    existing: Vec<UnitView>,  // live on target — what incoming might conflict with
}

#[derive(Deserialize)]
struct Replacement {
    /// hash of the target unit being superseded
    from: String,
    /// hash of the incoming unit replacing it
    to: String,
}

#[derive(Deserialize)]
struct MergeApplyRequest {
    from: String,
    into: String,
    /// incoming hashes to bring over as-is
    #[serde(default)]
    adopt: Vec<String>,
    /// incoming units that replace an existing target unit
    #[serde(default)]
    replace: Vec<Replacement>,
    source: String,
    summary: String,
}

#[derive(Deserialize)]
struct RetrieveRequest {
    query: String,
    #[serde(default = "default_max_units")]
    max_units: usize,
    #[serde(default = "default_branch")]
    branch: String,
    #[serde(default)]
    boost_types: Vec<UnitType>,
    #[serde(default)]
    ignore_pinning: bool,
}

#[derive(Deserialize)]
struct PurgeRequest {
    hash: String,
}

#[derive(Serialize)]
struct RetrievedUnitView {
    hash: String,
    #[serde(flatten)]
    unit: MemoryUnit,
    score: f64,
    // None = ranked normally by dense/BM25/rerank; Some = pulled in
    // because it's a 1-hop graph neighbor of a top-ranked unit.
    #[serde(skip_serializing_if = "Option::is_none")]
    via_edge_reason: Option<String>,
}

#[derive(Deserialize)]
struct StateAtTimeRequest {
    branch: String,
    target: chrono::DateTime<chrono::Utc>,
}

#[derive(Serialize)]
struct StateAtTimeResponse {
    resolved_at: Option<chrono::DateTime<chrono::Utc>>,
    units: Vec<UnitView>,
}

#[derive(Deserialize)]
struct SearchQuery {
    pattern: String,
    branch: Option<String>,
}

#[derive(Deserialize)]
struct CommitmentsDueQuery {
    #[serde(default = "default_branch")]
    branch: String,
    within: chrono::DateTime<chrono::Utc>,
}

type ApiError = (StatusCode, String);


fn default_max_units() -> usize {
    12
}

fn internal(e: impl std::fmt::Debug) -> ApiError {
    (StatusCode::INTERNAL_SERVER_ERROR, format!("{:?}", e))
}

fn check_branch(branch: &str) -> Result<(), ApiError> {
    if valid_branch_name(branch) {
        Ok(())
    } else {
        Err((StatusCode::BAD_REQUEST, format!("invalid branch name: {branch:?}")))
    }
}

async fn health() -> &'static str {
    "ok"
}

async fn branches(State(app): State<Arc<AppState>>) -> Result<Json<Vec<String>>, ApiError> {
    app.store.list_branches().map_err(internal).map(Json)
}

/// Checks whether an entity already exists for this name+type on a
/// branch, before capture.py decides whether to create a new one or
/// reuse the existing hash as an edge target.
async fn resolve_entity(
    State(app): State<Arc<AppState>>,
    Json(req): Json<ResolveEntityRequest>,
) -> Result<Json<Option<EntityView>>, ApiError> {
    let found = app.store.resolve_entity(&req.name, req.entity_type).map_err(internal)?;
    Ok(Json(found.map(|(hash, entity)| EntityView { hash, entity })))
}

/// Creates a new entity, or adds an alias to an existing one if the
/// name+type already resolves. Idempotent-ish: calling this twice with
/// the same name+type+alias converges to one entity record.
async fn put_entity(
    State(app): State<Arc<AppState>>,
    Json(req): Json<PutEntityRequest>,
) -> Result<Json<EntityView>, ApiError> {
    let hash = app.store.put_entity(&req.name, req.entity_type, req.alias.as_deref()).map_err(internal)?;
    let entity = app.store.get_entity(&hash).map_err(internal)?;
    Ok(Json(EntityView { hash, entity }))
}

/// All entities tracked, globally — used by capture.py to build the
/// known-entities prompt block with no branch argument needed.
async fn list_entities(
    State(app): State<Arc<AppState>>,
) -> Result<Json<Vec<EntityView>>, ApiError> {
    let entities = app.store.list_entities().map_err(internal)?;
    Ok(Json(entities.into_iter().map(|(hash, entity)| EntityView { hash, entity }).collect()))
}

async fn state(
    State(app): State<Arc<AppState>>,
    Query(q): Query<BranchQuery>,
) -> Result<Json<Vec<UnitView>>, ApiError> {
    check_branch(&q.branch)?;
    let units = app.store.current_state(&q.branch).map_err(internal)?;
    Ok(Json(units.into_iter().map(|(hash, unit)| UnitView { hash, unit }).collect()))
}

async fn remember(
    State(app): State<Arc<AppState>>,
    Json(req): Json<RememberRequest>,
) -> Result<Json<UnitView>, ApiError> {
    let mut unit = MemoryUnit::new(req.content, req.unit_type, req.provenance, req.source.clone());
    unit.deadline = req.deadline;
    unit.commitment_status = req.commitment_status;

    let hash = app.store.put(&unit).map_err(internal)?;

    let app2 = app.clone();
    let content = unit.content.clone();
    let embedding = tokio::task::spawn_blocking(move || app2.embedder.embed_document(&content))
        .await
        .map_err(internal)?
        .map_err(internal)?;
    app.store.put_embedding(&hash, &embedding).map_err(internal)?;

    let parent = app.store.head(&req.branch).map_err(internal)?;
    app.store
        .commit(&req.branch, &Commit::new(
            parent,
            vec![UnitChange::Added { hash: hash.clone() }],
            req.source,
            req.summary,
        ))
        .map_err(internal)?;

    Ok(Json(UnitView { hash, unit }))
}

async fn supersede(
    State(app): State<Arc<AppState>>,
    Json(req): Json<SupersedeRequest>,
) -> Result<Json<UnitView>, ApiError> {
    check_branch(&req.branch)?;

    let mut unit = MemoryUnit::new(req.content, req.unit_type, req.provenance, req.source.clone());
    unit.deadline = req.deadline;
    unit.commitment_status = req.commitment_status;

    let hash = app.store.put(&unit).map_err(internal)?;

    let app2 = app.clone();
    let content = unit.content.clone();
    let embedding = tokio::task::spawn_blocking(move || app2.embedder.embed_document(&content))
        .await
        .map_err(internal)?
        .map_err(internal)?;
    app.store.put_embedding(&hash, &embedding).map_err(internal)?;

    let parent = app.store.head(&req.branch).map_err(internal)?;
    app.store
        .commit(&req.branch, &Commit::new(
            parent,
            vec![UnitChange::Modified { from: req.from, to: hash.clone() }],
            req.source,
            req.summary,
        ))
        .map_err(internal)?;

    Ok(Json(UnitView { hash, unit }))
}

async fn forget(
    State(app): State<Arc<AppState>>,
    Json(req): Json<ForgetRequest>,
) -> Result<Json<serde_json::Value>, ApiError> {
    check_branch(&req.branch)?;
    let parent = app.store.head(&req.branch).map_err(internal)?;
    app.store
        .commit(&req.branch, &Commit::new(
            parent,
            vec![UnitChange::Superseded { hash: req.hash }],
            req.source,
            req.summary,
        ))
        .map_err(internal)?;

    Ok(Json(serde_json::json!({ "ok": true })))
}

/// Stores a relates_to edge between two already-committed units on a
/// branch. Deliberately NOT part of the commit/history graph — edges are
/// auxiliary retrieval structure, not versioned facts, so they don't
/// need their own commit entry. Content-addressable like everything
/// else in the store, so identical (from, to, reason) posted twice
/// dedupes to the same hash instead of piling up duplicates.
async fn add_edge(
    State(app): State<Arc<AppState>>,
    Json(req): Json<EdgeRequest>,
) -> Result<Json<EdgeView>, ApiError> {

    if !app.store.has(&req.from) {
        return Err((StatusCode::BAD_REQUEST, format!("unknown unit: {}", req.from)));
    }
    if !app.store.has(&req.to) {
        return Err((StatusCode::BAD_REQUEST, format!("unknown unit: {}", req.to)));
    }

    let edge = Edge::new(req.from, req.to, req.relation, req.reason);
    let hash = app.store.put_edge(&edge).map_err(internal)?;

    Ok(Json(EdgeView { hash, edge }))
}

async fn memory_search(
    State(app): State<Arc<AppState>>,
    Query(q): Query<SearchQuery>,
) -> Result<Json<Vec<UnitView>>, ApiError> {
    let branch = q.branch.as_deref().unwrap_or("main");
    check_branch(branch)?;
    let matches = app.store.search_state(branch, &q.pattern).map_err(internal)?;
    Ok(Json(matches.into_iter().map(|(hash, unit)| UnitView { hash, unit }).collect()))
}

async fn retrieve(
    State(app): State<Arc<AppState>>,
    Json(req): Json<RetrieveRequest>,
) -> Result<Json<Vec<RetrievedUnitView>>, ApiError> {
    check_branch(&req.branch)?;
    let units = app.store.current_state(&req.branch).map_err(internal)?;

    let (pinned, rest): (Vec<_>, Vec<_>) = if req.ignore_pinning {
        (Vec::new(), units)
    } else {
        units.into_iter().partition(|(_, u)| {
            matches!(u.unit_type, UnitType::Identity | UnitType::Preference)
        })
    };

    let mut out: Vec<RetrievedUnitView> = pinned
        .into_iter()
        .map(|(hash, unit)| RetrievedUnitView { hash, unit, score: PINNED_SENTINEL_SCORE, via_edge_reason: None })
        .collect();

    let app2 = app.clone();
    let query = req.query.clone();
    let query_embedding = tokio::task::spawn_blocking(move || app2.embedder.embed_query(&query))
        .await
        .map_err(internal)?
        .map_err(internal)?;
    let embeddings = app.store.embeddings_for(&rest).map_err(internal)?;
    let bm25_scores = app.store.bm25_scores(&req.branch, &req.query, DENSE_POOL_K).map_err(internal)?;

    let scored = memory_engine::retrieval::score(&req.query, &query_embedding, rest, &embeddings, &bm25_scores, &req.boost_types);
    let rerank_candidates: Vec<(String, MemoryUnit)> = scored
        .into_iter()
        .take(DENSE_POOL_K)
        .map(|s| (s.hash, s.unit))
        .collect();

    let app2 = app.clone();
    let query = req.query.clone();
    let contents: Vec<String> = rerank_candidates.iter().map(|(_, u)| u.content.clone()).collect();
    let rerank_scores = tokio::task::spawn_blocking(move || {
        let refs: Vec<&str> = contents.iter().map(|s| s.as_str()).collect();
        app2.reranker.rerank(&query, &refs)
    })
        .await
        .map_err(internal)?
        .map_err(internal)?;

    let mut reranked: Vec<(String, MemoryUnit, f32)> = rerank_candidates
        .into_iter()
        .zip(rerank_scores)
        .map(|((hash, unit), score)| (hash, unit, score))
        .collect();
    reranked.sort_by(|a, b| b.2.total_cmp(&a.2));

    // Unvalidated starting guess: relevant facts have scored 0.15–0.59 in
    // testing so far; clearly irrelevant ones 0.0001–0.03. Needs real tuning
    // against broader usage, same as MIN_BM25_SCORE/MIN_DENSE_SCORE before it.
    const MIN_RERANK_SCORE: f32 = 0.1;

    let remaining = req.max_units.saturating_sub(out.len());
    let ranked_units: Vec<(String, MemoryUnit, f32)> = reranked
        .into_iter()
        .filter(|(_, _, score)| *score >= MIN_RERANK_SCORE)
        .take(remaining)
        .collect();

    let seed_hashes: Vec<String> = ranked_units.iter().map(|(h, _, _)| h.clone()).collect();

    out.extend(
        ranked_units
            .into_iter()
            .map(|(hash, unit, score)| RetrievedUnitView { hash, unit, score: score as f64, via_edge_reason: None }),
    );

    // Graph expansion: pull in 1-hop neighbors of the ranked set that
    // didn't make it on their own — fills the remaining budget only,
    // never displaces a unit that scored well independently. Silent no-op
    // if the branch has no edges yet or the budget's already full.
    let slots_left = req.max_units.saturating_sub(out.len());
    if slots_left > 0 && !seed_hashes.is_empty() {
        let edges = app.store.list_edges().map_err(internal)?;
            let neighbors = entity_mediated_neighbors(&seed_hashes, &edges);

        let mut seen: std::collections::HashSet<String> = out.iter().map(|u| u.hash.clone()).collect();
        for (hash, relation, reason) in neighbors {
            if seen.contains(&hash) {
                continue;
            }
            // The neighbor hash might be a MemoryUnit or an Entity —
            // only units are retrievable as RetrievedUnitView content;
            // an Entity neighbor is a graph node, not directly
            // displayable the same way. Try unit first, skip silently
            // if it resolves to an entity instead (a future
            // enhancement could surface entity neighbors distinctly).
            if let Ok(unit) = app.store.get(&hash) {
                let tag = format!("{relation}: {reason}");
                out.push(RetrievedUnitView { hash: hash.clone(), unit, score: 0.0, via_edge_reason: Some(tag) });
                seen.insert(hash);
            }
            if out.len() >= req.max_units {
                break;
            }
        }
    }

    Ok(Json(out))
}

async fn history(
    State(app): State<Arc<AppState>>,
    Query(q): Query<BranchQuery>,
) -> Result<Json<Vec<CommitView>>, ApiError> {
    check_branch(&q.branch)?;
    let head = match app.store.head(&q.branch).map_err(internal)? {
        Some(h) => h,
        None => return Ok(Json(Vec::new())),
    };
    let commits = app.store.history(&head).map_err(internal)?;

    let mut out = Vec::with_capacity(commits.len());
    for (hash, commit) in commits {
        let mut changes = Vec::with_capacity(commit.changes.len());
        for change in commit.changes {
            // Best-effort: falls back to None rather than failing the whole
            // response if a referenced unit's content is unreachable (e.g.
            // an old purged hash) — type display degrades gracefully, the
            // timeline itself never breaks over one unresolvable entry.
            let lookup_hash = match &change {
                UnitChange::Added { hash } => Some(hash.clone()),
                UnitChange::Modified { to, .. } => Some(to.clone()),
                UnitChange::Superseded { hash } => Some(hash.clone()),
            };
            let unit_type = lookup_hash.and_then(|h| app.store.get(&h).ok().map(|u| u.unit_type));
            changes.push(ChangeView { change, unit_type });
        }
        out.push(CommitView {
            hash, parent: commit.parent, changes,
            source: commit.source, summary: commit.summary, created_at: commit.created_at,
        });
    }

    Ok(Json(out))
}

/// Dev-only: wipes every branch, not just one.
async fn reset(State(app): State<Arc<AppState>>) -> Result<Json<serde_json::Value>, ApiError> {
    app.store.reset().map_err(internal)?;
    Ok(Json(serde_json::json!({ "reset": true })))
}

async fn state_at_time(
    State(app): State<Arc<AppState>>,
    Json(req): Json<StateAtTimeRequest>,
) -> Result<Json<StateAtTimeResponse>, ApiError> {
    check_branch(&req.branch)?;
    match app.store.state_at_time(&req.branch, req.target).map_err(internal)? {
        Some((resolved_at, units)) => Ok(Json(StateAtTimeResponse {
            resolved_at: Some(resolved_at),
            units: units.into_iter().map(|(hash, unit)| UnitView { hash, unit }).collect(),
        })),
        None => Ok(Json(StateAtTimeResponse { resolved_at: None, units: vec![] })),
    }
}

async fn commitments_open(
    State(app): State<Arc<AppState>>,
    Query(q): Query<BranchQuery>,
) -> Result<Json<Vec<UnitView>>, ApiError> {
    check_branch(&q.branch)?;
    let units = app.store.open_commitments(&q.branch).map_err(internal)?;
    Ok(Json(units.into_iter().map(|(hash, unit)| UnitView { hash, unit }).collect()))
}

async fn commitments_due(
    State(app): State<Arc<AppState>>,
    Query(q): Query<CommitmentsDueQuery>,
) -> Result<Json<Vec<UnitView>>, ApiError> {
    check_branch(&q.branch)?;
    let units = app.store.open_commitments_due(&q.branch, q.within).map_err(internal)?;
    Ok(Json(units.into_iter().map(|(hash, unit)| UnitView { hash, unit }).collect()))
}

/// What merging `from` into `into` would bring over. Read-only.
async fn merge_preview(
    State(app): State<Arc<AppState>>,
    Query(q): Query<MergePreviewQuery>,
) -> Result<Json<MergePreview>, ApiError> {
    check_branch(&q.from)?;
    check_branch(&q.into)?;

    let source = app.store.current_state(&q.from).map_err(internal)?;
    let target = app.store.current_state(&q.into).map_err(internal)?;

    let target_hashes: std::collections::HashSet<&String> =
        target.iter().map(|(h, _)| h).collect();

    let incoming = source
        .iter()
        .filter(|(h, _)| !target_hashes.contains(h))
        .map(|(h, u)| UnitView { hash: h.clone(), unit: u.clone() })
        .collect();

    let existing = target
        .into_iter()
        .map(|(hash, unit)| UnitView { hash, unit })
        .collect();

    Ok(Json(MergePreview { incoming, existing }))
}

/// Applies a merge as a single commit on the target branch.
/// Nothing is deleted — replaced units are superseded and stay in history.
async fn merge_apply(
    State(app): State<Arc<AppState>>,
    Json(req): Json<MergeApplyRequest>,
) -> Result<Json<serde_json::Value>, ApiError> {
    check_branch(&req.from)?;
    check_branch(&req.into)?;

    let mut changes = Vec::new();

    for hash in &req.adopt {
        if !app.store.has(hash) {
            return Err((StatusCode::BAD_REQUEST, format!("unknown unit: {hash}")));
        }
        changes.push(UnitChange::Added { hash: hash.clone() });
    }

    for r in &req.replace {
        if !app.store.has(&r.to) {
            return Err((StatusCode::BAD_REQUEST, format!("unknown unit: {}", r.to)));
        }
        changes.push(UnitChange::Modified { from: r.from.clone(), to: r.to.clone() });
    }

    if changes.is_empty() {
        return Ok(Json(serde_json::json!({ "ok": true, "commit": null, "note": "nothing to merge" })));
    }

    let parent = app.store.head(&req.into).map_err(internal)?;
    let commit = app
        .store
        .commit(&req.into, &Commit::new(parent, changes, req.source.clone(), req.summary.clone()))
        .map_err(internal)?;

    Ok(Json(serde_json::json!({ "ok": true, "commit": commit })))
}

/// Hard-delete: the unit's content is genuinely removed from disk.
/// Callers are expected to have already soft-forgotten the unit (dropped
/// it from HEAD) — this endpoint only concerns itself with the object store.
async fn purge(
    State(app): State<Arc<AppState>>,
    Json(req): Json<PurgeRequest>,
) -> Result<Json<serde_json::Value>, ApiError> {
    app.store.purge_object(&req.hash).map_err(internal)?;
    Ok(Json(serde_json::json!({ "ok": true, "purged": req.hash })))
}

#[tokio::main]
async fn main() {
    let root = std::env::var("MEMORY_ROOT").unwrap_or_else(|_| "./memory-store".to_string());
    let store = MemoryStore::open(&root).expect("failed to open memory store");
    let embedder = Embedder::load().expect("failed to load embedder");
    let reranker = Reranker::load().expect("failed to load reranker");

    let _ = embedder.embed_query("warmup").expect("embedder warmup failed");
    let _ = reranker.rerank("warmup", &["warmup document"]).expect("reranker warmup failed");


    let app_state = Arc::new(AppState { store, embedder, reranker });

    let app = Router::new()
        .route("/health", get(health))
        .route("/branches", get(branches))
        .route("/state", get(state))
        .route("/remember", post(remember))
        .route("/supersede", post(supersede))
        .route("/forget", post(forget))
        .route("/edge", post(add_edge))
        .route("/retrieve", post(retrieve))
        .route("/history", get(history))
        .route("/reset", post(reset))
        .route("/merge/preview", get(merge_preview))
        .route("/merge/apply", post(merge_apply))
        .route("/purge", post(purge))
        .route("/search", get(memory_search))
        .route("/state-at-time", post(state_at_time))
        .route("/commitments/due", get(commitments_due))
        .route("/commitments/open", get(commitments_open))
        .route("/entity/resolve", post(resolve_entity))
        .route("/entity", post(put_entity))
        .route("/entities", get(list_entities))
        .with_state(app_state)
        .layer(CorsLayer::permissive());

    let listener = tokio::net::TcpListener::bind("127.0.0.1:8100").await.unwrap();
    println!("memory engine listening on http://127.0.0.1:8100 (store: {root})");
    axum::serve(listener, app).await.unwrap();
}