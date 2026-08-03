use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "snake_case")]
pub enum EntityType {
    Person,
    Project,
    Concept,
    Organization,
    Place,
    Animal,
    Other,
}

/// A resolved, canonical thing memory facts talk about — a person, a
/// project, a concept. Distinct from MemoryUnit: a unit is a fact stated
/// at a point in time; an entity is the persistent thing multiple facts
/// converge on. "Max," "the dog," and "my dog" should all resolve to one
/// Entity record, not three disconnected mentions.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Entity {
    pub name: String,
    pub entity_type: EntityType,
    pub aliases: Vec<String>,
    pub created_at: DateTime<Utc>,
}

impl Entity {
    pub fn new(name: String, entity_type: EntityType) -> Self {
        Self { name, entity_type, aliases: Vec::new(), created_at: Utc::now() }
    }

    /// Deterministic lookup key from name+type — NOT a content hash of the
    /// whole struct, which would change every time an alias is added.
    /// This is what the entity index is keyed on, separate from the
    /// content-addressed object hash of any specific version of the record.
    pub fn resolution_key(name: &str, entity_type: EntityType) -> String {
        format!("{:?}:{}", entity_type, name.trim().to_lowercase())
    }
}

/// A typed, temporally-valid relationship — between two entities, or
/// between a fact (MemoryUnit hash) and an entity it's about. `from`/`to`
/// are content hashes of either an Entity or a MemoryUnit; the store
/// doesn't need to know which, since both are looked up the same way
/// (content-addressed get()).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Edge {
    pub from: String,
    pub to: String,
    pub relation: String,   // short typed label, e.g. "has_pet", "works_on", "decided"
    pub reason: String,     // free-text explanation, for the trace UI
    pub t_valid: DateTime<Utc>,
    pub t_invalid: Option<DateTime<Utc>>,
    pub created_at: DateTime<Utc>,
}

impl Edge {
    pub fn new(from: String, to: String, relation: String, reason: String) -> Self {
        let now = Utc::now();
        Self { from, to, relation, reason, t_valid: now, t_invalid: None, created_at: now }
    }

    pub fn is_live(&self, at: DateTime<Utc>) -> bool {
        self.t_valid <= at && self.t_invalid.map_or(true, |inv| at < inv)
    }
}

/// Two-hop walk mediated through a shared entity: seed unit -> entity
/// (1st hop) -> other unit that also points at that same entity (2nd
/// hop). This is the actual payoff of entity-centric structure — two
/// facts about "Max" captured independently, weeks apart, on different
/// branches, never need a direct edge to each other. They both point at
/// the same Max entity node, and that shared node is what connects them.
/// Entity nodes themselves are never returned as retrievable content —
/// only the units that share an entity with a seed unit.
pub fn entity_mediated_neighbors(
    seed_hashes: &[String],
    all_edges: &[Edge],
) -> Vec<(String, String, String)> {
    let now = Utc::now();
    let live_edges: Vec<&Edge> = all_edges.iter().filter(|e| e.is_live(now)).collect();
    let seed_set: std::collections::HashSet<&str> =
        seed_hashes.iter().map(|s| s.as_str()).collect();

    // 1st hop: entities directly connected to a seed unit.
    let mut connected_entities: std::collections::HashSet<&str> = std::collections::HashSet::new();
    for edge in &live_edges {
        if seed_set.contains(edge.from.as_str()) {
            connected_entities.insert(edge.to.as_str());
        }
    }

    // 2nd hop: other units connected to those same entities.
    let mut out = Vec::new();
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
    for edge in &live_edges {
        if connected_entities.contains(edge.to.as_str())
            && !seed_set.contains(edge.from.as_str())
            && seen.insert(edge.from.clone())
        {
            out.push((edge.from.clone(), edge.relation.clone(), edge.reason.clone()));
        }
    }
    out
}