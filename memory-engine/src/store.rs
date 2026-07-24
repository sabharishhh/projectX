use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use serde::{de::DeserializeOwned, Serialize};
use sha2::{Digest, Sha256};

use crate::commit::{Commit, UnitChange};
use crate::unit::MemoryUnit;

#[derive(Debug)]
pub enum StoreError {
    Io(io::Error),
    Serde(serde_json::Error),
}

impl From<io::Error> for StoreError {
    fn from(e: io::Error) -> Self { StoreError::Io(e) }
}
impl From<serde_json::Error> for StoreError {
    fn from(e: serde_json::Error) -> Self { StoreError::Serde(e) }
}

/// Branch names become filenames under refs/, so they're restricted to
/// something path-safe — this also blocks path traversal via a crafted
/// branch name like "../../etc/passwd".
pub fn valid_branch_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && name.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

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

    /// Writes a commit and moves the given branch's HEAD to it.
    pub fn commit(&self, branch: &str, commit: &Commit) -> Result<String, StoreError> {
        let hash = self.put_commit(commit)?;
        self.set_head(branch, &hash)?;
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

    // --- state resolution ---

    /// Replays history oldest-first to produce the units live at `commit_hash`.
    /// Branch-agnostic by design — it just walks parent pointers from
    /// whatever commit it's given.
    pub fn state_at(&self, commit_hash: &str) -> Result<Vec<(String, MemoryUnit)>, StoreError> {
        let mut live: Vec<String> = Vec::new();
        for (_, commit) in self.history(commit_hash)?.into_iter().rev() {
            for change in commit.changes {
                match change {
                    UnitChange::Added { hash } => live.push(hash),
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

    fn get_object<T: DeserializeOwned>(&self, hash: &str) -> Result<T, StoreError> {
        let bytes = fs::read(self.path_for(hash))?;
        Ok(serde_json::from_slice(&bytes)?)
    }

    fn path_for(&self, hash: &str) -> PathBuf {
        self.objects_dir.join(&hash[..2]).join(&hash[2..])
    }
}

fn hash_bytes(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hasher.finalize().iter().map(|b| format!("{:02x}", b)).collect()
}