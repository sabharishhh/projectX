use std::sync::Arc;

use axum::{
    extract::{Query, State},
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use memory_engine::{valid_branch_name, Commit, MemoryStore, MemoryUnit, Provenance, UnitChange, UnitType};
use serde::{Deserialize, Serialize};
use tower_http::cors::CorsLayer;

struct AppState {
    store: MemoryStore,
}

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
struct RetrieveRequest {
    query: String,
    #[serde(default = "default_max_units")]
    max_units: usize,
    #[serde(default = "default_branch")]
    branch: String,
}
fn default_max_units() -> usize {
    12
}

#[derive(Serialize)]
struct UnitView {
    hash: String,
    #[serde(flatten)]
    unit: MemoryUnit,
}

#[derive(Serialize)]
struct CommitView {
    hash: String,
    #[serde(flatten)]
    commit: Commit,
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

type ApiError = (StatusCode, String);

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
    check_branch(&req.branch)?;
    let unit = MemoryUnit::new(req.content, req.unit_type, req.provenance, req.source.clone());
    let hash = app.store.put(&unit).map_err(internal)?;

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
    let unit = MemoryUnit::new(req.content, req.unit_type, req.provenance, req.source.clone());
    let hash = app.store.put(&unit).map_err(internal)?;

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

async fn retrieve(
    State(app): State<Arc<AppState>>,
    Json(req): Json<RetrieveRequest>,
) -> Result<Json<Vec<UnitView>>, ApiError> {
    check_branch(&req.branch)?;
    let units = app.store.current_state(&req.branch).map_err(internal)?;

    let (pinned, rest): (Vec<_>, Vec<_>) = units.into_iter().partition(|(_, u)| {
        matches!(u.unit_type, UnitType::Identity | UnitType::Preference)
    });

    let mut out: Vec<UnitView> = pinned.into_iter().map(|(hash, unit)| UnitView { hash, unit }).collect();

    let scored = memory_engine::retrieval::score(&req.query, &rest);
    let remaining = req.max_units.saturating_sub(out.len());
    out.extend(scored.into_iter().take(remaining).map(|s| UnitView { hash: s.hash, unit: s.unit }));

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
    Ok(Json(commits.into_iter().map(|(hash, commit)| CommitView { hash, commit }).collect()))
}

/// Dev-only: wipes every branch, not just one.
async fn reset(State(app): State<Arc<AppState>>) -> Result<Json<serde_json::Value>, ApiError> {
    app.store.reset().map_err(internal)?;
    Ok(Json(serde_json::json!({ "reset": true })))
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

#[tokio::main]
async fn main() {
    let root = std::env::var("MEMORY_ROOT").unwrap_or_else(|_| "./memory-store".to_string());
    let store = MemoryStore::open(&root).expect("failed to open memory store");
    let app_state = Arc::new(AppState { store });

    let app = Router::new()
        .route("/health", get(health))
        .route("/branches", get(branches))
        .route("/state", get(state))
        .route("/remember", post(remember))
        .route("/supersede", post(supersede))
        .route("/forget", post(forget))
        .route("/retrieve", post(retrieve))
        .route("/history", get(history))
        .route("/reset", post(reset))
        .route("/merge/preview", get(merge_preview))
        .route("/merge/apply", post(merge_apply))
        .with_state(app_state)
        .layer(CorsLayer::permissive());

    let listener = tokio::net::TcpListener::bind("127.0.0.1:8100").await.unwrap();
    println!("memory engine listening on http://127.0.0.1:8100 (store: {root})");
    axum::serve(listener, app).await.unwrap();
}