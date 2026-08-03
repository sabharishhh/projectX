<script>
  import Dropdown from './ui/Dropdown.svelte';
  import Tag from './ui/Tag.svelte';
  import { reveal, arrive } from '../motion.js';

  let { history = [] } = $props();

  const branchItems = $derived.by(() => {
    const seen = [];
    for (const e of history) if (!seen.includes(e.branch)) seen.push(e.branch);
    return seen.map((b) => ({ id: b, text: b }));
  });

  let selectedBranch = $state(null);
  $effect(() => {
    if (!selectedBranch && branchItems.length) selectedBranch = branchItems[0].id;
  });

  const branchHistory = $derived(
    history
      .filter((e) => e.branch === selectedBranch)
      .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
  );

  let selectedEntry = $state(null);

  function verb(change) {
    if (change.kind === 'added') return 'Remembered';
    if (change.kind === 'modified') return 'Changed';
    if (change.kind === 'superseded') return 'Forgot';
    return change.kind;
  }
  function commitVerb(entry) {
    const kinds = new Set(entry.changes.map((c) => c.kind));
    return kinds.size === 1 ? verb(entry.changes[0]) : 'Updated';
  }
  function isCommitment(entry) {
    return entry.changes.some((c) => c.unit_type === 'commitment');
  }
  function relativeTime(iso) {
    const diffMs = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    if (days < 30) return `${days}d ago`;
    return new Date(iso).toLocaleDateString();
  }
  function selectEntry(entry) {
    selectedEntry = selectedEntry?.hash === entry.hash ? null : entry;
  }
</script>

<div class="timeline-view">
  {#if branchItems.length > 1}
    <Dropdown titleText="Branch" items={branchItems} bind:selectedId={selectedBranch} />
  {:else if branchItems.length === 1}
    <div class="single-branch"><Tag type="blue">{branchItems[0].text}</Tag></div>
  {/if}

  {#if branchHistory.length === 0}
    <p class="empty">No history on this branch yet.</p>
  {:else}
    <ol class="rail">
      {#each branchHistory as entry (entry.hash)}
        <li in:reveal>
          <button
            class="event"
            class:commitment={isCommitment(entry)}
            class:selected={selectedEntry?.hash === entry.hash}
            onclick={() => selectEntry(entry)}
          >
            <span class="dot" class:diamond={isCommitment(entry)}></span>
            <span class="event-body">
              <span class="event-verb">{commitVerb(entry)}</span>
              <span class="event-summary">
                {entry.changes[0]?.content ?? ''}{entry.changes.length > 1 ? ` +${entry.changes.length - 1} more` : ''}
              </span>
              <time class="event-time">{relativeTime(entry.created_at)}</time>
            </span>
          </button>

          {#if selectedEntry?.hash === entry.hash}
            <div class="detail-card" in:arrive>
              <div class="detail-header">
                <span class="detail-verb">{commitVerb(entry)}</span>
                <time class="detail-time">{new Date(entry.created_at).toLocaleString()}</time>
              </div>
              <ul class="detail-changes">
                {#each entry.changes as c}
                  <li>{verb(c)} — <span class="technical">{c.unit_type}</span>: {c.content}</li>
                {/each}
              </ul>
            </div>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
</div>

<style>
  .timeline-view { display: flex; flex-direction: column; gap: var(--space-3); }
  .single-branch { margin-bottom: var(--space-2); }
  .empty { color: var(--text-secondary); font-size: var(--size-meta); font-style: italic; }

  .rail { list-style: none; margin: 0; padding: 0 0 0 var(--space-2); position: relative; }
  .rail::before {
    content: ''; position: absolute; left: 9px; top: 6px; bottom: 6px;
    width: 2px; background: var(--border-strong);
  }
  .rail li { position: relative; margin: 0 0 var(--space-3); }

  .event {
    display: flex; align-items: flex-start; gap: var(--space-3);
    width: 100%; text-align: left; background: none; border: none;
    padding: var(--space-1) 0; cursor: pointer;
  }
  .event:hover .event-summary { color: var(--text-primary); }

  .dot {
    flex-shrink: 0; width: 10px; height: 10px; margin-top: 4px;
    border-radius: 50%; background: var(--accent-primary);
    border: 2px solid var(--surface-card);
    box-shadow: 0 0 0 2px var(--border-strong);
    z-index: 1;
  }
  .dot.diamond { border-radius: 2px; transform: rotate(45deg); }

  .event-body { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .event-verb { font-size: var(--size-meta); font-weight: var(--weight-semibold); color: var(--text-primary); }
  .event-summary {
    font-size: var(--size-meta); color: var(--text-secondary);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%;
  }
  .event-time { font-family: var(--font-technical); font-size: var(--size-caption); color: var(--text-muted); }
  .event.selected .event-verb { color: var(--accent-primary); }

  .detail-card {
    margin: var(--space-2) 0 0 var(--space-5);
    background: var(--surface-sunken); border-radius: var(--radius-md); padding: var(--space-3);
  }
  .detail-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--space-2); }
  .detail-verb { font-weight: var(--weight-semibold); font-size: var(--size-meta); }
  .detail-time { font-family: var(--font-technical); font-size: var(--size-caption); color: var(--text-muted); }
  .detail-changes { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-1); }
  .detail-changes li { font-size: var(--size-meta); color: var(--text-secondary); line-height: var(--leading-tight); }
  .detail-changes .technical { font-family: var(--font-technical); color: var(--text-muted); }
</style>