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
        .with_state(app_state)
        .layer(CorsLayer::permissive());

    let listener = tokio::net::TcpListener::bind("127.0.0.1:8100").await.unwrap();
    println!("memory engine listening on http://127.0.0.1:8100 (store: {root})");
    axum::serve(listener, app).await.unwrap();
}