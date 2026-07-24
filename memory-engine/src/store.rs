use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};

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
    objects_dir: PathBuf,
}

impl MemoryStore {
    /// Creates <root>/objects/ if it doesn't exist.
    pub fn open(root: impl AsRef<Path>) -> Result<Self, StoreError> {
        let objects_dir = root.as_ref().join("objects");
        fs::create_dir_all(&objects_dir)?;
        Ok(Self { objects_dir })
    }

    /// Writes the unit and returns its hash. Writing the same unit
    /// twice is a no-op that returns the same hash.
    pub fn put(&self, unit: &MemoryUnit) -> Result<String, StoreError> {
        let json = serde_json::to_vec(unit)?;
        let hash = hash_bytes(&json);
        let path = self.path_for(&hash);

        if !path.exists() {
            fs::create_dir_all(path.parent().unwrap())?;
            fs::write(&path, &json)?;
        }
        Ok(hash)
    }

    pub fn get(&self, hash: &str) -> Result<MemoryUnit, StoreError> {
        let bytes = fs::read(self.path_for(hash))?;
        Ok(serde_json::from_slice(&bytes)?)
    }

    pub fn has(&self, hash: &str) -> bool {
        self.path_for(hash).exists()
    }

    /// Fans out by the first two hex chars, like git, so no single
    /// directory ends up with thousands of files.
    fn path_for(&self, hash: &str) -> PathBuf {
        self.objects_dir.join(&hash[..2]).join(&hash[2..])
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