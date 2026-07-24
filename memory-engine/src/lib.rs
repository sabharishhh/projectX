pub mod store;
pub mod unit;

pub use store::{MemoryStore, StoreError};
pub use unit::{MemoryUnit, Provenance, UnitType};

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn sample() -> MemoryUnit {
        MemoryUnit::new(
            "prefers short, direct answers",
            UnitType::Preference,
            Provenance::Stated,
            "conv-1",
        )
    }

    #[test]
    fn round_trips_a_unit() {
        let dir = tempdir().unwrap();
        let store = MemoryStore::open(dir.path()).unwrap();

        let unit = sample();
        let hash = store.put(&unit).unwrap();

        assert!(store.has(&hash));
        assert_eq!(store.get(&hash).unwrap(), unit);
    }

    #[test]
    fn identical_units_dedupe_to_one_object() {
        let dir = tempdir().unwrap();
        let store = MemoryStore::open(dir.path()).unwrap();

        let unit = sample();
        let a = store.put(&unit).unwrap();
        let b = store.put(&unit).unwrap();

        assert_eq!(a, b);
    }

    #[test]
    fn different_content_yields_different_hash() {
        let dir = tempdir().unwrap();
        let store = MemoryStore::open(dir.path()).unwrap();

        let a = store.put(&sample()).unwrap();
        let mut other = sample();
        other.content = "prefers long, detailed answers".into();
        let b = store.put(&other).unwrap();

        assert_ne!(a, b);
    }
}