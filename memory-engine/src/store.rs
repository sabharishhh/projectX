use std::collections::HashMap;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde::{de::DeserializeOwned, Serialize};
use sha2::{Digest, Sha256};

use crate::commit::{Commit, UnitChange};
use crate::unit::{MemoryUnit, UnitType, CommitmentStatus};
use crate::entity::{Entity, EntityType, Edge};

use regex::Regex;
use crate::bm25::BM25Store;

#[derive(Debug)]
pub enum StoreError {
    Io(io::Error),
    Serde(serde_json::Error),
    Regex(regex::Error),
    Corrupted(String, String), // (expected_hash, actual_hash) — content read from
    // a hash-addressed path no longer matches that hash
    InvalidHash(String), // not a well-formed content hash (empty, non-hex, too short)
    HeadMoved(String), // branch name — commit's parent no longer matches HEAD,
    // another writer committed to this branch first
    HashStillLive(String), // hash — purge was requested for a unit still
    // referenced by some branch's current state
}

impl From<io::Error> for StoreError {
    fn from(e: io::Error) -> Self { StoreError::Io(e) }
}
impl From<serde_json::Error> for StoreError {
    fn from(e: serde_json::Error) -> Self { StoreError::Serde(e) }
}

impl From<regex::Error> for StoreError {
    fn from(e: regex::Error) -> Self {
        StoreError::Regex(e)
    }
}

/// Branch names become filenames under refs/, so they're restricted to
/// something path-safe — this also blocks path traversal via a crafted
/// branch name like "../../etc/passwd".
pub fn valid_branch_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && name.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

// How many commits state_at() will replay from the nearest checkpoint (or
// genesis, if none exists yet) before a fresh checkpoint gets written.
// Keeps state resolution's worst case bounded regardless of how much total
// history accumulates over time — without this, state_at() replays the
// entire commit history from the beginning on every single call, which
// only gets slower as a personal memory store does what it's meant to do:
// accumulate history over months or years.
const CHECKPOINT_INTERVAL: usize = 20;

pub struct MemoryStore {
    root: PathBuf,
    objects_dir: PathBuf,
    bm25: BM25Store,
    // Serializes every mutation that does read-current-state-then-write
    // (commit/set_head, entity index, edges index, purge) against every
    // other such mutation on this store, process-wide. Without it, two
    // concurrent writers can both read the same HEAD and both write —
    // the second write silently wins and the first commit becomes
    // unreachable. A single coarse-grained mutex is enough here: this
    // store backs one process's personal memory, not a high-throughput
    // multi-tenant system, so serializing all writes costs nothing
    // observable while making every mutation safe by construction.
    write_lock: Mutex<()>,
}

impl MemoryStore {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, StoreError> {
        let root = root.as_ref().to_path_buf();
        let objects_dir = root.join("objects");
        fs::create_dir_all(&objects_dir)?;
        let bm25 = BM25Store::new(&root);
        Ok(Self { root, objects_dir, bm25, write_lock: Mutex::new(()) })
    }

    // --- units ---

    pub fn put(&self, unit: &MemoryUnit) -> Result<String, StoreError> {
        self.put_object(unit)
    }

    pub fn get(&self, hash: &str) -> Result<MemoryUnit, StoreError> {
        self.get_object(hash)
    }

    // --- commits ---

    pub fn put_commit(&self, commit: &Commit) -> Result<String, StoreError> {
        self.put_object(commit)
    }

    pub fn get_commit(&self, hash: &str) -> Result<Commit, StoreError> {
        self.get_object(hash)
    }

    pub fn history(&self, from: &str) -> Result<Vec<(String, Commit)>, StoreError> {
        let mut out = Vec::new();
        let mut cursor = Some(from.to_string());
        while let Some(hash) = cursor {
            let commit = self.get_commit(&hash)?;
            cursor = commit.parent.clone();
            out.push((hash, commit));
        }
        Ok(out)
    }

    // --- refs (one HEAD pointer per branch) ---

    fn ref_path(&self, branch: &str) -> PathBuf {
        self.root.join("refs").join(branch)
    }

    pub fn head(&self, branch: &str) -> Result<Option<String>, StoreError> {
        match fs::read_to_string(self.ref_path(branch)) {
            Ok(s) => Ok(Some(s.trim().to_string())),
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(None),
            Err(e) => Err(e.into()),
        }
    }

    pub fn set_head(&self, branch: &str, hash: &str) -> Result<(), StoreError> {
        atomic_write(&self.ref_path(branch), hash.as_bytes())
    }

    /// Writes a commit and moves the given branch's HEAD to it. Also checks
    /// whether this commit is due for a checkpoint (see maybe_checkpoint) —
    /// keeps state_at()'s replay bounded as history grows, transparently,
    /// with no change to this method's callers or return value.
    ///
    /// Holds `write_lock` for its whole read-HEAD/write-HEAD span and
    /// verifies `commit.parent` still matches HEAD before writing — without
    /// both, two concurrent commits on the same branch can each read the
    /// same HEAD and each write; the second `set_head` silently wins and
    /// the first commit becomes unreachable (never showing up in
    /// `current_state`/`state_at` again, despite being on disk). With the
    /// check, the loser gets `StoreError::HeadMoved` back and can retry
    /// against the new HEAD instead of silently disappearing.
    pub fn commit(&self, branch: &str, commit: &Commit) -> Result<String, StoreError> {
        let _guard = self.write_lock.lock().unwrap();

        let current_head = self.head(branch)?;
        if current_head != commit.parent {
            return Err(StoreError::HeadMoved(branch.to_string()));
        }

        let hash = self.put_commit(commit)?;
        self.set_head(branch, &hash)?;
        self.maybe_checkpoint(&hash)?;

        // Index whatever units this commit actually introduced as live
        // content — Superseded changes reference a hash going OUT of HEAD,
        // nothing new to index for those.
        for change in &commit.changes {
            let unit_hash = match change {
                UnitChange::Added { hash } => Some(hash),
                UnitChange::Modified { to, .. } => Some(to),
                UnitChange::Superseded { .. } => None,
            };
            if let Some(h) = unit_hash {
                let unit = self.get(h)?;
                self.bm25.upsert(branch, h, &unit.content)?;
            }
        }

        Ok(hash)
    }

    /// BM25 relevance scores for a branch's content, hash -> score. One
    /// signal among several in retrieval::score() — dense catches meaning,
    /// this catches exact/rare terms a paraphrase-tolerant embedding can
    /// under-rank.
    pub fn bm25_scores(&self, branch: &str, query: &str, limit: usize) -> Result<HashMap<String, f64>, StoreError> {
         self.bm25.search(branch, query, limit)
     }

    // --- entities ---

    fn entity_index_path(&self) -> PathBuf {
        self.root.join("entities").join("index.json")
    }

    /// resolution_key -> current entity object hash, per branch. Mutable —
    /// overwritten in place, same pattern as refs/HEAD — because an
    /// entity's canonical identity persists across updates (new aliases,
    /// etc.) even though each version is stored content-addressed.
    fn load_entity_index(&self) -> Result<HashMap<String, String>, StoreError> {
        match fs::read(self.entity_index_path()) {
            Ok(bytes) => Ok(serde_json::from_slice(&bytes)?),
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(HashMap::new()),
            Err(e) => Err(e.into()),
        }
    }

    fn save_entity_index(&self, index: &HashMap<String, String>) -> Result<(), StoreError> {
        atomic_write(&self.entity_index_path(), &serde_json::to_vec(index)?)
    }

    /// Looks up an existing entity by name+type on a branch. Returns the
    /// (hash, Entity) if one already resolves to this key — the check
    /// capture.py's entity-resolution step calls before deciding whether
    /// to create a new entity or reuse an existing one.
    pub fn resolve_entity(&self, name: &str, entity_type: EntityType) -> Result<Option<(String, Entity)>, StoreError> {
        let key = Entity::resolution_key(name, entity_type);
        let index = self.load_entity_index()?;
        match index.get(&key) {
            Some(hash) => Ok(Some((hash.clone(), self.get_object(hash)?))),
            None => Ok(None),
        }
    }

    /// Creates a new entity, or updates an existing one's aliases if
    /// `name`+`entity_type` already resolves. Always writes a fresh
    /// content-addressed object (entities are otherwise immutable, same as
    /// units), then repoints the mutable index entry at the new hash.
    pub fn put_entity(&self, name: &str, entity_type: EntityType, new_alias: Option<&str>) -> Result<String, StoreError> {
        let _guard = self.write_lock.lock().unwrap();
        let key = Entity::resolution_key(name, entity_type);
        let mut index = self.load_entity_index()?;

        let entity = match index.get(&key) {
            Some(existing_hash) => {
                let mut e: Entity = self.get_object(existing_hash)?;
                if let Some(alias) = new_alias {
                    if !e.aliases.iter().any(|a| a.eq_ignore_ascii_case(alias)) {
                        e.aliases.push(alias.to_string());
                    }
                }
                e
            }
            None => Entity::new(name.to_string(), entity_type),
        };

        let hash = self.put_object(&entity)?;
        index.insert(key, hash.clone());
        self.save_entity_index(&index)?;
        Ok(hash)
    }

    pub fn get_entity(&self, hash: &str) -> Result<Entity, StoreError> {
        self.get_object(hash)
    }

    pub fn list_entities(&self) -> Result<Vec<(String, Entity)>, StoreError> {
        let index = self.load_entity_index()?;
        index.values().map(|h| self.get_object(h).map(|e| (h.clone(), e))).collect()
    }

    // --- edges ---

    fn edges_index_path(&self) -> PathBuf {
        self.root.join("edges").join("index.json")
    }

    /// Stores an edge content-addressable, appends its hash to a flat
    /// per-branch index. Edges live outside the commit/tree structure —
    /// they're auxiliary retrieval and relationship structure, not
    /// versioned facts, so no history replay or checkpointing needed.
    pub fn put_edge(&self, edge: &Edge) -> Result<String, StoreError> {
        let _guard = self.write_lock.lock().unwrap();
        let hash = self.put_object(edge)?;
        let path = self.edges_index_path();
        let mut hashes: Vec<String> = match fs::read(&path) {
            Ok(bytes) => serde_json::from_slice(&bytes)?,
            Err(e) if e.kind() == io::ErrorKind::NotFound => Vec::new(),
            Err(e) => return Err(e.into()),
        };
        if !hashes.contains(&hash) {
            hashes.push(hash.clone());
            atomic_write(&path, &serde_json::to_vec(&hashes)?)?;
        }
        Ok(hash)
    }

    pub fn list_edges(&self) -> Result<Vec<Edge>, StoreError> {
        let path = self.edges_index_path();
        let hashes: Vec<String> = match fs::read(&path) {
            Ok(bytes) => serde_json::from_slice(&bytes)?,
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(Vec::new()),
            Err(e) => return Err(e.into()),
        };
        hashes.iter().map(|h| self.get_object(h)).collect()
    }

    /// Marks an edge invalid as of now, by rewriting it with t_invalid set
    /// and appending the new version's hash to the index — the old (still
    /// valid-at-the-time) version stays retrievable by its original hash,
    /// same non-destructive philosophy as unit supersession.
    pub fn invalidate_edge(&self, edge_hash: &str) -> Result<String, StoreError> {
        let mut edge: Edge = self.get_object(edge_hash)?;
        edge.t_invalid = Some(chrono::Utc::now());
        self.put_edge(&edge)
    }

    /// Every branch that has at least one commit. A branch exists the
    /// moment something is first committed to it — no separate creation step.
    pub fn list_branches(&self) -> Result<Vec<String>, StoreError> {
        let refs_dir = self.root.join("refs");
        if !refs_dir.exists() {
            return Ok(Vec::new());
        }
        let mut out = Vec::new();
        for entry in fs::read_dir(refs_dir)? {
            if let Some(name) = entry?.file_name().to_str() {
                out.push(name.to_string());
            }
        }
        out.sort();
        Ok(out)
    }

    pub fn has(&self, hash: &str) -> bool {
        match self.path_for(hash) {
            Ok(path) => path.exists(),
            Err(_) => false, // malformed hash can never exist
        }
    }

    // --- checkpointing ---

    fn checkpoint_path(&self, commit_hash: &str) -> PathBuf {
        self.root.join("checkpoints").join(commit_hash)
    }

    fn load_checkpoint(&self, commit_hash: &str) -> Result<Option<Vec<String>>, StoreError> {
        match fs::read(self.checkpoint_path(commit_hash)) {
            Ok(bytes) => Ok(Some(serde_json::from_slice(&bytes)?)),
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(None),
            Err(e) => Err(e.into()),
        }
    }

    fn save_checkpoint(&self, commit_hash: &str, live: &[String]) -> Result<(), StoreError> {
        atomic_write(&self.checkpoint_path(commit_hash), &serde_json::to_vec(live)?)
    }

    /// Walks backward at most CHECKPOINT_INTERVAL commits from `commit_hash`,
    /// looking for an existing checkpoint. If one's found within range,
    /// nothing to do. If genesis is reached first, the chain's still short
    /// enough that a checkpoint wouldn't help yet. Only when the full
    /// interval is walked without finding either does this commit get a
    /// fresh checkpoint written — via state_at(), which at this point is
    /// itself bounded to the same interval, so this stays cheap.
    fn maybe_checkpoint(&self, commit_hash: &str) -> Result<(), StoreError> {
        let mut cursor = Some(commit_hash.to_string());
        let mut steps = 0;
        loop {
            let hash = match cursor {
                Some(h) => h,
                None => return Ok(()), // reached genesis within the interval
            };
            if self.checkpoint_path(&hash).exists() {
                return Ok(()); // an earlier checkpoint is within range — not due yet
            }
            if steps >= CHECKPOINT_INTERVAL {
                break;
            }
            let commit = self.get_commit(&hash)?;
            cursor = commit.parent.clone();
            steps += 1;
        }
        let live = self.state_at(commit_hash)?;
        let hashes: Vec<String> = live.into_iter().map(|(h, _)| h).collect();
        self.save_checkpoint(commit_hash, &hashes)?;
        Ok(())
    }

    // --- state resolution ---

    /// Resolves the units live at `commit_hash`. Walks backward from
    /// `commit_hash` toward genesis, stopping early if a saved checkpoint
    /// is found — replays forward from there instead of from the very
    /// beginning of history every time. Falls back to a full replay from
    /// genesis when no checkpoint exists yet (e.g. a short chain, or a
    /// store predating checkpointing). Branch-agnostic by design — it just
    /// walks parent pointers from whatever commit it's given.
    pub fn state_at(&self, commit_hash: &str) -> Result<Vec<(String, MemoryUnit)>, StoreError> {
        let mut stack: Vec<Commit> = Vec::new();
        let mut cursor = Some(commit_hash.to_string());
        let mut live: Vec<String> = Vec::new();

        while let Some(hash) = cursor {
            if let Some(checkpoint) = self.load_checkpoint(&hash)? {
                live = checkpoint;
                break;
            }
            let commit = self.get_commit(&hash)?;
            cursor = commit.parent.clone();
            stack.push(commit);
        }

        for commit in stack.into_iter().rev() {
            for change in commit.changes {
                match change {
                    UnitChange::Added { hash } => {
                        if !live.contains(&hash) {
                            live.push(hash);
                        }
                    }
                    UnitChange::Modified { from, to } => {
                        live.retain(|h| h != &from);
                        live.push(to);
                    }
                    UnitChange::Superseded { hash } => live.retain(|h| h != &hash),
                }
            }
        }

        live.into_iter().map(|h| self.get(&h).map(|u| (h, u))).collect()
    }

    pub fn current_state(&self, branch: &str) -> Result<Vec<(String, MemoryUnit)>, StoreError> {
        match self.head(branch)? {
            Some(h) => self.state_at(&h),
            None => Ok(Vec::new()),
        }
    }

    /// Exact/pattern search over a branch's current (live) state. Read-only,
    /// scoped to units currently in HEAD — soft-forgotten (superseded) units
    /// are deliberately excluded, same privacy boundary as everything else the
    /// agent can already read. Full history search is a separate, unbuilt
    /// capability, not this one.
    pub fn search_state(&self, branch: &str, pattern: &str) -> Result<Vec<(String, MemoryUnit)>, StoreError> {
        let re = Regex::new(pattern)?;
        let state = self.current_state(branch)?;
        Ok(state.into_iter().filter(|(_, unit)| re.is_match(&unit.content)).collect())
    }

    /// Every currently-open commitment on a branch, regardless of deadline —
    /// a distinct question from open_commitments_due (which is specifically
    /// deadline-gated, for the "what's coming up soon" surfacing case).
    /// Used for narrowing resolution candidates, where deadline is
    /// irrelevant to whether a commitment is still open.
    pub fn open_commitments(&self, branch: &str) -> Result<Vec<(String, MemoryUnit)>, StoreError> {
        let state = self.current_state(branch)?;
        Ok(state
            .into_iter()
            .filter(|(_, u)| {
                u.unit_type == UnitType::Commitment
                    && u.commitment_status == Some(CommitmentStatus::Open)
            })
            .collect())
    }

    /// Every currently-open commitment whose deadline falls at or before
    /// `within`, across a branch's live state. Deterministic filter, same
    /// category as search_state() — plain, exact conditions, auditable, no
    /// LLM judgment anywhere in producing this result.
    pub fn open_commitments_due(
        &self,
        branch: &str,
        within: chrono::DateTime<chrono::Utc>,
    ) -> Result<Vec<(String, MemoryUnit)>, StoreError> {
        let state = self.current_state(branch)?;
        Ok(state
            .into_iter()
            .filter(|(_, u)| {
                u.unit_type == UnitType::Commitment
                    && u.commitment_status == Some(CommitmentStatus::Open)
                    && u.deadline.map_or(false, |d| d <= within)
            })
            .collect())
    }

    // --- reset (dev only — wipes every branch, not just one) ---

    pub fn reset(&self) -> Result<(), StoreError> {
        if self.objects_dir.exists() {
            fs::remove_dir_all(&self.objects_dir)?;
        }
        fs::create_dir_all(&self.objects_dir)?;

        let refs_dir = self.root.join("refs");
        if refs_dir.exists() {
            fs::remove_dir_all(&refs_dir)?;
        }

        let checkpoints_dir = self.root.join("checkpoints");
        if checkpoints_dir.exists() {
            fs::remove_dir_all(&checkpoints_dir)?;
        }

        let edges_dir = self.root.join("edges");
        if edges_dir.exists() {
            fs::remove_dir_all(&edges_dir)?;
        }

        let entities_dir = self.root.join("entities");
        if entities_dir.exists() {
            fs::remove_dir_all(&entities_dir)?;
        }

        Ok(())
    }

    /// Resolves state as it was at a specific point in time — walks branch
    /// history backward from HEAD to find the latest commit at or before
    /// `target`, then delegates to state_at() (which already benefits from
    /// checkpointing). Returns the actual commit timestamp used alongside the
    /// state, since `target` snaps to the nearest real commit at or before
    /// it, not the exact instant requested — a caller asking "as of March 15"
    /// needs to know the answer is really "as of the last change before that
    /// date," not silently pretend precision that doesn't exist.
    pub fn state_at_time(
        &self,
        branch: &str,
        target: chrono::DateTime<chrono::Utc>,
    ) -> Result<Option<(chrono::DateTime<chrono::Utc>, Vec<(String, MemoryUnit)>)>, StoreError> {
        let mut cursor = self.head(branch)?;
        while let Some(hash) = cursor {
            let commit = self.get_commit(&hash)?;
            if commit.created_at <= target {
                let state = self.state_at(&hash)?;
                return Ok(Some((commit.created_at, state)));
            }
            cursor = commit.parent.clone();
        }
        Ok(None) // nothing existed on this branch at or before `target`
    }

    // --- internals ---

    fn put_object<T: Serialize>(&self, value: &T) -> Result<String, StoreError> {
        let json = serde_json::to_vec(value)?;
        let hash = hash_bytes(&json);
        let path = self.path_for(&hash)?; // hash_bytes always yields a valid hex hash
        if !path.exists() {
            fs::create_dir_all(path.parent().unwrap())?;
            fs::write(&path, &json)?;
        }
        Ok(hash)
    }

    /// Re-hashes the bytes read from a hash-addressed path and confirms
    /// they still match before deserializing — content-addressing without
    /// this check is a guarantee in name only. Catches disk corruption, a
    /// partial write from a crash mid-save, or manual tampering, instead
    /// of silently deserializing whatever's actually on disk.
    fn get_object<T: DeserializeOwned>(&self, hash: &str) -> Result<T, StoreError> {
        let bytes = fs::read(self.path_for(hash)?)?;
        let actual = hash_bytes(&bytes);
        if actual != hash {
            return Err(StoreError::Corrupted(hash.to_string(), actual));
        }
        Ok(serde_json::from_slice(&bytes)?)
    }

    /// Validates before slicing — `hash` can be arbitrary, unauthenticated
    /// caller-supplied text (e.g. `/purge`'s request body), and byte-index
    /// slicing on it directly used to panic the whole process on an empty
    /// string or a hash shorter than 2 bytes, or on a multi-byte UTF-8
    /// character straddling the split point (`&hash[..2]` panics with
    /// "not a char boundary" if byte 2 isn't one). Requiring ASCII hex
    /// digits rules out both: hex digits are single-byte, so any byte
    /// index within the string is automatically a char boundary.
    fn path_for(&self, hash: &str) -> Result<PathBuf, StoreError> {
        if hash.len() < 3 || !hash.chars().all(|c| c.is_ascii_hexdigit()) {
            return Err(StoreError::InvalidHash(hash.to_string()));
        }
        Ok(self.objects_dir.join(&hash[..2]).join(&hash[2..]))
    }

    fn embedding_path(&self, hash: &str) -> Result<PathBuf, StoreError> {
        if hash.len() < 3 || !hash.chars().all(|c| c.is_ascii_hexdigit()) {
            return Err(StoreError::InvalidHash(hash.to_string()));
        }
        Ok(self.objects_dir.join(&hash[..2]).join(format!("{}.emb", &hash[2..])))
    }

    /// Permanently removes a unit's content from disk. Only safe once a
    /// unit is genuinely out of every branch's HEAD (soft-forgotten) —
    /// callers were previously just "expected" to ensure that themselves,
    /// with nothing enforcing it; purging a unit that's still live left
    /// every future `state_at`/`current_state` call on that branch hard-
    /// failing (`get` on a hash whose object file is now gone). Checking
    /// here, under the same write_lock as commit(), makes that ordering a
    /// guarantee instead of a caller convention, and closes the window
    /// where a concurrent commit could re-add the hash between the check
    /// and the delete.
    pub fn purge_object(&self, hash: &str) -> Result<(), StoreError> {
        let _guard = self.write_lock.lock().unwrap();
        for branch in self.list_branches()? {
            if self.current_state(&branch)?.iter().any(|(h, _)| h == hash) {
                return Err(StoreError::HashStillLive(hash.to_string()));
            }
        }
        let path = self.path_for(hash)?;
        if path.exists() {
            fs::remove_file(path)?;
        }
        Ok(())
    }

    /// Caches a unit's embedding. Call once, at write time (alongside
    /// `put`) — never needs re-calling for the same hash, since content
    /// is immutable once hashed.
    pub fn put_embedding(&self, hash: &str, embedding: &[f32]) -> Result<(), StoreError> {
        let path = self.embedding_path(hash)?;
        fs::create_dir_all(path.parent().unwrap())?;
        let bytes: Vec<u8> = embedding.iter().flat_map(|f| f.to_le_bytes()).collect();
        fs::write(path, bytes)?;
        Ok(())
    }

    pub fn get_embedding(&self, hash: &str) -> Result<Option<Vec<f32>>, StoreError> {
        match fs::read(self.embedding_path(hash)?) {
            Ok(bytes) => Ok(Some(
                bytes
                    .chunks_exact(4)
                    .map(|c| f32::from_le_bytes(c.try_into().unwrap()))
                    .collect(),
            )),
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(None),
            Err(e) => Err(e.into()),
        }
    }

    /// Embeddings for a batch of units, keyed by hash. Units with no cached
    /// embedding yet (e.g. written before this feature existed) are simply
    /// absent from the map — retrieval::score treats a missing entry as
    /// "fall back to BM25 for this unit," never panics on the gap.
    pub fn embeddings_for(
        &self,
        units: &[(String, MemoryUnit)],
    ) -> Result<HashMap<String, Vec<f32>>, StoreError> {
        let mut out = HashMap::new();
        for (hash, _) in units {
            if let Some(emb) = self.get_embedding(hash)? {
                out.insert(hash.clone(), emb);
            }
        }
        Ok(out)
    }

}

/// Write-to-temp-then-rename. Applies to every *mutable* file this store
/// maintains (refs/HEAD, entity index, edges index, checkpoints) — unlike
/// content-addressed objects, these get overwritten in place and have no
/// hash to self-verify on read, so a plain `fs::write` that crashes or
/// loses power mid-write leaves a truncated file with no way to detect
/// the corruption later (a truncated HEAD hash fails `get_commit` with a
/// confusing "Corrupted"/not-found error; a truncated index.json fails
/// `serde_json` parsing and hard-fails the whole entity/edge subsystem).
/// `rename` on the same filesystem is atomic, so a crash mid-write leaves
/// either the old file or the new one, never a partial one.
fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), StoreError> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let file_name = path.file_name().and_then(|n| n.to_str()).unwrap_or("tmp");
    let tmp_path = path.with_file_name(format!(".{file_name}.tmp-{}", std::process::id()));
    fs::write(&tmp_path, bytes)?;
    fs::rename(&tmp_path, path)?;
    Ok(())
}

fn hash_bytes(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hasher.finalize().iter().map(|b| format!("{:02x}", b)).collect()
}