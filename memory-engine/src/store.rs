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

    /// Walks parent pointers, newest first.
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

    // --- HEAD ---

    pub fn set_head(&self, hash: &str) -> Result<(), StoreError> {
        fs::write(self.root.join("HEAD"), hash)?;
        Ok(())
    }

    /// None if nothing has been committed yet.
    pub fn head(&self) -> Result<Option<String>, StoreError> {
        match fs::read_to_string(self.root.join("HEAD")) {
            Ok(s) => Ok(Some(s.trim().to_string())),
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(None),
            Err(e) => Err(e.into()),
        }
    }

    /// Convenience: write a commit and move HEAD to it in one step.
    pub fn commit(&self, commit: &Commit) -> Result<String, StoreError> {
        let hash = self.put_commit(commit)?;
        self.set_head(&hash)?;
        Ok(hash)
    }

    pub fn has(&self, hash: &str) -> bool {
        self.path_for(hash).exists()
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

    /// Replays history oldest-first to produce the units currently live at `commit_hash`.
    /// Returns (hash, unit) pairs — superseded and replaced versions are excluded.
    pub fn state_at(&self, commit_hash: &str) -> Result<Vec<(String, MemoryUnit)>, StoreError> {
        let mut live: Vec<String> = Vec::new();

        // history() is newest-first; replay in the opposite order.
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

        live.into_iter()
            .map(|h| self.get(&h).map(|u| (h, u)))
            .collect()
    }

    /// Current state at HEAD. Empty if nothing is committed yet.
    pub fn current_state(&self) -> Result<Vec<(String, MemoryUnit)>, StoreError> {
        match self.head()? {
            Some(h) => self.state_at(&h),
            None => Ok(Vec::new()),
        }
    }

    /// Dev-only: wipes all objects and HEAD. Not part of the product surface —
    /// hard-delete of individual units is a separate, deliberate operation.
    pub fn reset(&self) -> Result<(), StoreError> {
        if self.objects_dir.exists() {
            fs::remove_dir_all(&self.objects_dir)?;
        }
        fs::create_dir_all(&self.objects_dir)?;

        let head = self.root.join("HEAD");
        if head.exists() {
            fs::remove_file(head)?;
        }
        Ok(())
    }

}

fn hash_bytes(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hasher
        .finalize()
        .iter()
        .map(|b| format!("{:02x}", b))
        .collect()
}