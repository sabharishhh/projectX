pub mod commit;
pub mod retrieval;
pub mod store;
pub mod unit;

pub use commit::{Commit, UnitChange};
pub use store::{valid_branch_name, MemoryStore, StoreError};
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
        let c1 = store.commit("main", &Commit::new(
            None,
            vec![UnitChange::Added { hash: first_unit.clone() }],
            "conv-1",
            "learned they prefer short, direct answers",
        )).unwrap();

        let mut revised = sample();
        revised.content = "prefers long, detailed answers".into();
        let second_unit = store.put(&revised).unwrap();

        let c2 = store.commit("main", &Commit::new(
            Some(c1.clone()),
            vec![UnitChange::Modified { from: first_unit, to: second_unit }],
            "conv-2",
            "answer-length preference flipped from short to long",
        )).unwrap();

        assert_eq!(store.head("main").unwrap(), Some(c2.clone()));
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
        assert!(store.head("main").unwrap().is_none());
    }

    #[test]
    fn state_reflects_modifications_not_stale_versions() {
        let dir = tempdir().unwrap();
        let store = MemoryStore::open(dir.path()).unwrap();

        let old = store.put(&sample()).unwrap();
        let c1 = store.commit("main", &Commit::new(
            None,
            vec![UnitChange::Added { hash: old.clone() }],
            "conv-1",
            "learned answer-length preference",
        )).unwrap();

        let mut revised = sample();
        revised.content = "prefers long, detailed answers".into();
        let new = store.put(&revised).unwrap();

        store.commit("main", &Commit::new(
            Some(c1),
            vec![UnitChange::Modified { from: old, to: new.clone() }],
            "conv-2",
            "preference flipped to long answers",
        )).unwrap();

        let state = store.current_state("main").unwrap();
        assert_eq!(state.len(), 1);
        assert_eq!(state[0].0, new);
    }

    #[test]
    fn superseded_units_drop_out_of_state_but_stay_readable() {
        let dir = tempdir().unwrap();
        let store = MemoryStore::open(dir.path()).unwrap();

        let hash = store.put(&sample()).unwrap();
        let c1 = store.commit("main", &Commit::new(
            None,
            vec![UnitChange::Added { hash: hash.clone() }],
            "conv-1",
            "learned a preference",
        )).unwrap();

        store.commit("main", &Commit::new(
            Some(c1),
            vec![UnitChange::Superseded { hash: hash.clone() }],
            "conv-2",
            "user asked to forget their answer-length preference",
        )).unwrap();

        assert!(store.current_state("main").unwrap().is_empty());
        assert!(store.has(&hash));
    }

    // --- branch isolation ---

    #[test]
    fn branches_are_isolated_from_each_other() {
        let dir = tempdir().unwrap();
        let store = MemoryStore::open(dir.path()).unwrap();

        let work_unit = MemoryUnit::new("works at a startup", UnitType::Identity, Provenance::Stated, "c1");
        let work_hash = store.put(&work_unit).unwrap();
        store.commit("work", &Commit::new(
            None,
            vec![UnitChange::Added { hash: work_hash.clone() }],
            "c1",
            "learned employer",
        )).unwrap();

        let personal_unit = MemoryUnit::new("has a dog named Max", UnitType::Relationship, Provenance::Stated, "c2");
        let personal_hash = store.put(&personal_unit).unwrap();
        store.commit("personal", &Commit::new(
            None,
            vec![UnitChange::Added { hash: personal_hash.clone() }],
            "c2",
            "learned about their dog",
        )).unwrap();

        let work_state = store.current_state("work").unwrap();
        let personal_state = store.current_state("personal").unwrap();

        assert_eq!(work_state.len(), 1);
        assert_eq!(work_state[0].0, work_hash);
        assert_eq!(personal_state.len(), 1);
        assert_eq!(personal_state[0].0, personal_hash);

        // an untouched branch stays empty
        assert!(store.current_state("main").unwrap().is_empty());
    }

    #[test]
    fn list_branches_reflects_only_committed_branches() {
        let dir = tempdir().unwrap();
        let store = MemoryStore::open(dir.path()).unwrap();

        assert!(store.list_branches().unwrap().is_empty());

        let hash = store.put(&sample()).unwrap();
        store.commit("main", &Commit::new(
            None, vec![UnitChange::Added { hash: hash.clone() }], "c1", "seed",
        )).unwrap();
        store.commit("work", &Commit::new(
            None, vec![UnitChange::Added { hash }], "c2", "seed",
        )).unwrap();

        let branches = store.list_branches().unwrap();
        assert_eq!(branches, vec!["main".to_string(), "work".to_string()]);
    }

    #[test]
    fn purge_removes_object_after_soft_forget() {
        let dir = tempdir().unwrap();
        let store = MemoryStore::open(dir.path()).unwrap();

        let hash = store.put(&sample()).unwrap();
        let c1 = store.commit("main", &Commit::new(
            None, vec![UnitChange::Added { hash: hash.clone() }], "c1", "seed",
        )).unwrap();
        store.commit("main", &Commit::new(
            Some(c1), vec![UnitChange::Superseded { hash: hash.clone() }], "c2", "forgot it",
        )).unwrap();

        assert!(store.has(&hash)); // soft-forgotten, still on disk
        store.purge_object(&hash).unwrap();
        assert!(!store.has(&hash)); // genuinely gone now

        // state resolution still works fine — history walk never needed
        // to re-fetch the purged unit's content
        assert!(store.current_state("main").unwrap().is_empty());
    }

    #[test]
    fn rejects_unsafe_branch_names() {
        assert!(valid_branch_name("main"));
        assert!(valid_branch_name("work-project_2"));
        assert!(!valid_branch_name(""));
        assert!(!valid_branch_name("../../etc/passwd"));
        assert!(!valid_branch_name("has spaces"));
    }
}