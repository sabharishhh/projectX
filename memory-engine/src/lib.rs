pub mod commit;
pub mod store;
pub mod unit;
pub mod retrieval;

pub use commit::{Commit, UnitChange};
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

    #[test]
    fn commits_chain_into_history() {
        let dir = tempdir().unwrap();
        let store = MemoryStore::open(dir.path()).unwrap();

        let first_unit = store.put(&sample()).unwrap();
        let c1 = store.commit(&Commit::new(
            None,
            vec![UnitChange::Added { hash: first_unit.clone() }],
            "conv-1",
            "learned they prefer short, direct answers",
        )).unwrap();

        let mut revised = sample();
        revised.content = "prefers long, detailed answers".into();
        let second_unit = store.put(&revised).unwrap();

        let c2 = store.commit(&Commit::new(
            Some(c1.clone()),
            vec![UnitChange::Modified { from: first_unit, to: second_unit }],
            "conv-2",
            "answer-length preference flipped from short to long",
        )).unwrap();

        assert_eq!(store.head().unwrap(), Some(c2.clone()));

        let history = store.history(&c2).unwrap();
        assert_eq!(history.len(), 2);
        assert_eq!(history[0].0, c2);
        assert_eq!(history[1].0, c1);
        assert!(history[1].1.parent.is_none());
    }

    #[test]
    fn head_is_none_before_first_commit() {
        let dir = tempdir().unwrap();
        let store = MemoryStore::open(dir.path()).unwrap();
        assert!(store.head().unwrap().is_none());
    }

    #[test]
    fn state_reflects_modifications_not_stale_versions() {
        let dir = tempdir().unwrap();
        let store = MemoryStore::open(dir.path()).unwrap();

        let old = store.put(&sample()).unwrap();
        let c1 = store.commit(&Commit::new(
            None,
            vec![UnitChange::Added { hash: old.clone() }],
            "conv-1",
            "learned answer-length preference",
        )).unwrap();

        let mut revised = sample();
        revised.content = "prefers long, detailed answers".into();
        let new = store.put(&revised).unwrap();

        store.commit(&Commit::new(
            Some(c1),
            vec![UnitChange::Modified { from: old, to: new.clone() }],
            "conv-2",
            "preference flipped to long answers",
        )).unwrap();

        let state = store.current_state().unwrap();
        assert_eq!(state.len(), 1);
        assert_eq!(state[0].0, new);
        assert_eq!(state[0].1.content, "prefers long, detailed answers");
    }

    #[test]
    fn superseded_units_drop_out_of_state_but_stay_readable() {
        let dir = tempdir().unwrap();
        let store = MemoryStore::open(dir.path()).unwrap();

        let hash = store.put(&sample()).unwrap();
        let c1 = store.commit(&Commit::new(
            None,
            vec![UnitChange::Added { hash: hash.clone() }],
            "conv-1",
            "learned a preference",
        )).unwrap();

        store.commit(&Commit::new(
            Some(c1),
            vec![UnitChange::Superseded { hash: hash.clone() }],
            "conv-2",
            "user asked to forget their answer-length preference",
        )).unwrap();

        assert!(store.current_state().unwrap().is_empty());
        // soft-forget: gone from HEAD, still in the store
        assert!(store.has(&hash));
        assert_eq!(store.get(&hash).unwrap().content, sample().content);
    }

}