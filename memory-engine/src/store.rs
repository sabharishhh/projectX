use std::collections::HashMap;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use serde::{de::DeserializeOwned, Serialize};
use sha2::{Digest, Sha256};

use crate::commit::{Commit, UnitChange};
use crate::unit::MemoryUnit;

use regex::Regex;

#[derive(Debug)]
pub enum StoreError {
    Io(io::Error),
    Serde(serde_json::Error),
    Regex(regex::Error),
    Corrupted(String, String), // (expected_hash, actual_hash) — content read from
    // a hash-addressed path no longer matches that hash
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
}

impl MemoryStore {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, StoreError> {
        let root = root.as_ref().to_path_buf();
        let objects_dir = root.join("objects");
        fs::create_dir_all(&objects_dir)?;
        Ok(Self { root, objects_dir })
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
        let path = self.ref_path(branch);
        fs::create_dir_all(path.parent().unwrap())?;
        fs::write(path, hash)?;
        Ok(())
    }

    /// Writes a commit and moves the given branch's HEAD to it. Also checks
    /// whether this commit is due for a checkpoint (see maybe_checkpoint) —
    /// keeps state_at()'s replay bounded as history grows, transparently,
    /// with no change to this method's callers or return value.
    pub fn commit(&self, branch: &str, commit: &Commit) -> Result<String, StoreError> {
        let hash = self.put_commit(commit)?;
        self.set_head(branch, &hash)?;
        self.maybe_checkpoint(&hash)?;
        Ok(hash)
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
        self.path_for(hash).exists()
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
        let path = self.checkpoint_path(commit_hash);
        fs::create_dir_all(path.parent().unwrap())?;
        fs::write(path, serde_json::to_vec(live)?)?;
        Ok(())
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
        Ok(())
    }

    // --- internals ---

    fn put_object<T: Serialize>(&self, value: &T) -> Result<String, StoreError> {
        let json = serde_json::to_vec(value)?;
        let hash = hash_bytes(&json);
        let path = self.path_for(&hash);
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
        let bytes = fs::read(self.path_for(hash))?;
        let actual = hash_bytes(&bytes);
        if actual != hash {
            return Err(StoreError::Corrupted(hash.to_string(), actual));
        }
        Ok(serde_json::from_slice(&bytes)?)
    }

    fn path_for(&self, hash: &str) -> PathBuf {
        self.objects_dir.join(&hash[..2]).join(&hash[2..])
    }

    fn embedding_path(&self, hash: &str) -> PathBuf {
        self.objects_dir.join(&hash[..2]).join(format!("{}.emb", &hash[2..]))
    }

    /// Permanently removes a unit's content from disk. Safe to call once a
    /// unit is already out of HEAD (superseded) — nothing in state
    /// resolution ever re-fetches a superseded unit's content, only its
    /// hash inside historical commit records, so this can't break replay.
    pub fn purge_object(&self, hash: &str) -> Result<(), StoreError> {
        let path = self.path_for(hash);
        if path.exists() {
            fs::remove_file(path)?;
        }
        Ok(())
    }

    /// Caches a unit's embedding. Call once, at write time (alongside
    /// `put`) — never needs re-calling for the same hash, since content
    /// is immutable once hashed.
    pub fn put_embedding(&self, hash: &str, embedding: &[f32]) -> Result<(), StoreError> {
        let path = self.embedding_path(hash);
        fs::create_dir_all(path.parent().unwrap())?;
        let bytes: Vec<u8> = embedding.iter().flat_map(|f| f.to_le_bytes()).collect();
        fs::write(path, bytes)?;
        Ok(())
    }

    pub fn get_embedding(&self, hash: &str) -> Result<Option<Vec<f32>>, StoreError> {
        match fs::read(self.embedding_path(hash)) {
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

fn hash_bytes(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hasher.finalize().iter().map(|b| format!("{:02x}", b)).collect()
}