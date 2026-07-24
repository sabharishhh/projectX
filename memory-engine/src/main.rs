use std::sync::Arc;

use axum::{
    extract::State,
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use memory_engine::{Commit, MemoryStore, MemoryUnit, Provenance, UnitChange, UnitType};
use serde::{Deserialize, Serialize};
use tower_http::cors::CorsLayer;

struct AppState {
    store: MemoryStore,
}

#[derive(Deserialize)]
struct RememberRequest {
    content: String,
    unit_type: UnitType,
    provenance: Provenance,
    source: String,
    /// Plain-language description of what changed, for the commit.
    summary: String,
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
struct SupersedeRequest {
    /// hash of the unit being replaced
    from: String,
    content: String,
    unit_type: UnitType,
    provenance: Provenance,
    source: String,
    summary: String,
}

#[derive(Deserialize)]
struct ForgetRequest {
    hash: String,
    source: String,
    summary: String,
}

#[derive(Deserialize)]
struct RetrieveRequest {
    query: String,
    #[serde(default = "default_max_units")]
    max_units: usize,
}

type ApiError = (StatusCode, String);

fn default_max_units() -> usize {
    12
}

fn internal(e: impl std::fmt::Debug) -> ApiError {
    (StatusCode::INTERNAL_SERVER_ERROR, format!("{:?}", e))
}

async fn health() -> &'static str {
    "ok"
}

/// Everything the system currently believes.
async fn state(State(app): State<Arc<AppState>>) -> Result<Json<Vec<UnitView>>, ApiError> {
    let units = app.store.current_state().map_err(internal)?;
    Ok(Json(
        units
            .into_iter()
            .map(|(hash, unit)| UnitView { hash, unit })
            .collect(),
    ))
}

/// Store a new fact and commit it.
async fn remember(
    State(app): State<Arc<AppState>>,
    Json(req): Json<RememberRequest>,
) -> Result<Json<UnitView>, ApiError> {
    let unit = MemoryUnit::new(req.content, req.unit_type, req.provenance, req.source.clone());
    let hash = app.store.put(&unit).map_err(internal)?;

    let parent = app.store.head().map_err(internal)?;
    app.store
        .commit(&Commit::new(
            parent,
            vec![UnitChange::Added { hash: hash.clone() }],
            req.source,
            req.summary,
        ))
        .map_err(internal)?;

    Ok(Json(UnitView { hash, unit }))
}

/// Replace a unit with a new version. The old one stays in history.
async fn supersede(
    State(app): State<Arc<AppState>>,
    Json(req): Json<SupersedeRequest>,
) -> Result<Json<UnitView>, ApiError> {
    let unit = MemoryUnit::new(req.content, req.unit_type, req.provenance, req.source.clone());
    let hash = app.store.put(&unit).map_err(internal)?;

    let parent = app.store.head().map_err(internal)?;
    app.store
        .commit(&Commit::new(
            parent,
            vec![UnitChange::Modified {
                from: req.from,
                to: hash.clone(),
            }],
            req.source,
            req.summary,
        ))
        .map_err(internal)?;

    Ok(Json(UnitView { hash, unit }))
}

/// Soft-forget: drops out of HEAD, stays readable in history.
async fn forget(
    State(app): State<Arc<AppState>>,
    Json(req): Json<ForgetRequest>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let parent = app.store.head().map_err(internal)?;
    app.store
        .commit(&Commit::new(
            parent,
            vec![UnitChange::Superseded { hash: req.hash }],
            req.source,
            req.summary,
        ))
        .map_err(internal)?;

    Ok(Json(serde_json::json!({ "ok": true })))
}

async fn history(State(app): State<Arc<AppState>>) -> Result<Json<Vec<CommitView>>, ApiError> {
    let head = match app.store.head().map_err(internal)? {
        Some(h) => h,
        None => return Ok(Json(Vec::new())),
    };
    let commits = app.store.history(&head).map_err(internal)?;
    Ok(Json(
        commits
            .into_iter()
            .map(|(hash, commit)| CommitView { hash, commit })
            .collect(),
    ))
}

/// Scored, budgeted retrieval for injecting into a conversation.
/// Identity and preference units are always included, unscored — they're
/// cheap and broadly useful, per the spec's "pinned set" rule.
async fn retrieve(
    State(app): State<Arc<AppState>>,
    Json(req): Json<RetrieveRequest>,
) -> Result<Json<Vec<UnitView>>, ApiError> {
    let units = app.store.current_state().map_err(internal)?;

    let (pinned, rest): (Vec<_>, Vec<_>) = units.into_iter().partition(|(_, u)| {
        matches!(u.unit_type, UnitType::Identity | UnitType::Preference)
    });

    let mut out: Vec<UnitView> = pinned
        .into_iter()
        .map(|(hash, unit)| UnitView { hash, unit })
        .collect();

    let scored = memory_engine::retrieval::score(&req.query, &rest);
    let remaining = req.max_units.saturating_sub(out.len());
    out.extend(
        scored
            .into_iter()
            .take(remaining)
            .map(|s| UnitView { hash: s.hash, unit: s.unit }),
    );

    Ok(Json(out))
}

/// Dev-only: wipes the entire store.
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
        .route("/state", get(state))
        .route("/remember", post(remember))
        .route("/history", get(history))
        .route("/reset", post(reset))
        .route("/supersede", post(supersede))
        .route("/forget", post(forget))
        .route("/retrieve", post(retrieve))
        .with_state(app_state)
        .layer(CorsLayer::permissive());

    let listener = tokio::net::TcpListener::bind("127.0.0.1:8100")
        .await
        .unwrap();
    println!("memory engine listening on http://127.0.0.1:8100 (store: {root})");
    axum::serve(listener, app).await.unwrap();
}