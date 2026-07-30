<script>
  import Collapsible from './Collapsible.svelte';
  import { reveal } from '$lib/motion.js';

  let { memory = [], history = [], onopensource = () => {}, onToggle } = $props();

  let view = $state('current'); // 'current' | 'timeline'
  let selectedEntry = $state(null);

  const ORDER = ['identity', 'preference', 'project', 'decision', 'relationship'];
  const grouped = $derived(
    ORDER.map((type) => ({ type, items: memory.filter((u) => u.unit_type === type) }))
         .filter((g) => g.items.length)
  );

  function verb(change) {
    if (change.kind === 'added') return 'Remembered';
    if (change.kind === 'modified') return 'Changed';
    if (change.kind === 'superseded') return 'Forgot';
    return change.kind;
  }

  function commitVerb(entry) {
    const kinds = new Set(entry.changes.map((c) => c.kind));
    if (kinds.size === 1) return verb(entry.changes[0]);
    return 'Updated';
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

  // --- graph layout ---
  const ROW_HEIGHT = 34;
  const LANE_SPACING = 90;
  const LANE_MARGIN = 40;
  const LABEL_HEIGHT = 24;
  const PALETTE = [
    'var(--accent-memory)', 'var(--accent-search)',
    '#d97757', '#7c9885', '#8b7ec8', '#c98a5e',
  ];

  const uniqueBranches = $derived.by(() => {
    const seen = [];
    for (const e of history) if (!seen.includes(e.branch)) seen.push(e.branch);
    return seen;
  });

  function branchColor(branch) {
    return PALETTE[uniqueBranches.indexOf(branch) % PALETTE.length];
  }

  function laneX(branch) {
    return LANE_MARGIN + uniqueBranches.indexOf(branch) * LANE_SPACING;
  }

  const graphWidth = $derived(LANE_MARGIN * 2 + uniqueBranches.length * LANE_SPACING);
  const graphHeight = $derived(LABEL_HEIGHT + history.length * ROW_HEIGHT + 20);

  const lanes = $derived.by(() => {
    return uniqueBranches.map((branch) => {
      const rows = history
        .map((e, i) => ({ e, i }))
        .filter(({ e }) => e.branch === branch);
      const top = LABEL_HEIGHT + rows[0].i * ROW_HEIGHT + ROW_HEIGHT / 2;
      const bottom = LABEL_HEIGHT + rows[rows.length - 1].i * ROW_HEIGHT + ROW_HEIGHT / 2;
      return { branch, x: laneX(branch), color: branchColor(branch), top, height: bottom - top };
    });
  });
</script>

<div class="panel">
  <div class="panel-header">
    <div class="brand">Memory</div>
    <button class="icon-btn" onclick={onToggle} title="Close memory panel" aria-label="Close memory panel">
      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
        <line x1="15" y1="3" x2="15" y2="21"></line>
      </svg>
    </button>
  </div>

  <div class="view-toggle">
    <button class:active={view === 'current'} onclick={() => (view = 'current')}>Current</button>
    <button class:active={view === 'timeline'} onclick={() => { view = 'timeline'; selectedEntry = null; }}>Timeline</button>
  </div>

  {#if view === 'current'}
    {#if grouped.length === 0}
      <p class="empty">Nothing remembered yet.</p>
    {/if}

    {#each grouped as group (group.type)}
      <div class="group">
        <Collapsible
          label={group.type}
          count={group.items.length}
          accent="var(--accent-memory)"
          open={group.type === 'identity'}
          boxed={false}
        >
          <ul>
            {#each group.items as u (u.hash)}
              <li in:reveal class:inferred={u.provenance === 'inferred'}>
                <span
                  class="content {u.provenance === 'inferred' ? 'provenance-inferred' : 'provenance-stated'}"
                >
                  {u.content}
                </span>
                <button class="source technical" title={u.source} onclick={() => onopensource(u.source)}>
                  {u.hash.slice(0, 8)}
                </button>
              </li>
            {/each}
          </ul>
        </Collapsible>
      </div>
    {/each}
  {:else}
    {#if history.length === 0}
      <p class="empty">No history yet.</p>
    {:else}
      <div class="graph-scroll">
        <div class="graph" style="width:{graphWidth}px; height:{graphHeight}px">
          {#each lanes as lane (lane.branch)}
            <div class="lane-label" style="left:{lane.x}px">{lane.branch}</div>
            <div
              class="lane-line"
              style="left:{lane.x}px; top:{lane.top}px; height:{lane.height}px; background:{lane.color}"
            ></div>
          {/each}

          {#each history as entry, i (entry.hash)}
            <button
              class="node"
              class:selected={selectedEntry?.hash === entry.hash}
              style="left:{laneX(entry.branch)}px; top:{LABEL_HEIGHT + i * ROW_HEIGHT + ROW_HEIGHT / 2}px; background:{branchColor(entry.branch)}"
              data-preview="{commitVerb(entry)} — {entry.summary}"
              onclick={() => (selectedEntry = selectedEntry?.hash === entry.hash ? null : entry)}
              aria-label="{commitVerb(entry)}: {entry.summary}"
            ></button>
          {/each}
        </div>
      </div>

      {#if selectedEntry}
        <div class="detail-card" in:reveal>
          <div class="detail-header">
            <span class="detail-verb">{commitVerb(selectedEntry)}</span>
            <span class="branch-tag">{selectedEntry.branch}</span>
            <button class="icon-btn small" onclick={() => (selectedEntry = null)} aria-label="Close">×</button>
          </div>
          <div class="detail-summary">{selectedEntry.summary}</div>
          <div class="detail-time">{new Date(selectedEntry.created_at).toLocaleString()}</div>
          <ul class="detail-changes">
            {#each selectedEntry.changes as change, i (i)}
              <li>{verb(change)}{change.kind === 'modified' ? ` (${change.from.slice(0,8)} → ${change.to.slice(0,8)})` : ` (${change.hash.slice(0,8)})`}</li>
            {/each}
          </ul>
          <button class="source technical" title={selectedEntry.source} onclick={() => onopensource(selectedEntry.source)}>
            source: {selectedEntry.source.slice(0, 8)}
          </button>
        </div>
      {/if}
    {/if}
  {/if}
</div>

<style>
  .panel { display:flex; flex-direction:column; }

  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding-bottom: var(--space-3);
    margin-bottom: var(--space-3);
    border-bottom: 0.5px solid var(--border-hairline);
  }

  .brand {
    font-weight: 600;
    font-size: 0.95rem;
    letter-spacing: -0.01em;
  }

  .icon-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    height: 2rem;
    padding: 0;
    background: none;
    border: none;
    color: var(--text-secondary);
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .icon-btn.small { width: 1.4rem; height: 1.4rem; font-size: 1rem; }

  .icon-btn svg {
    width: 1.25rem;
    height: 1.25rem;
    flex-shrink: 0;
  }

  .icon-btn:hover {
    background: var(--surface-sunken);
    color: var(--text-primary);
  }

  .view-toggle {
    display: flex;
    gap: var(--space-2);
    margin-bottom: var(--space-3);
  }
  .view-toggle button {
    flex: 1;
    padding: var(--space-2);
    border: 0.5px solid var(--border-hairline);
    background: none;
    color: var(--text-secondary);
    border-radius: var(--radius-sm);
    font-size: var(--size-meta);
    cursor: pointer;
  }
  .view-toggle button.active {
    background: var(--surface-sunken);
    color: var(--text-primary);
    font-weight: 600;
  }

  .group + .group {
    margin-top:var(--space-3);
    padding-top:var(--space-2);
    border-top:0.5px solid var(--border-hairline);
  }

  ul { list-style:none; margin:0; padding:0; }

  li {
    display:grid;
    grid-template-columns:minmax(0, 1fr) auto;
    gap:var(--space-3);
    align-items:baseline;
    padding:var(--space-3) 0 var(--space-3) var(--space-3);
    border-left:2px solid var(--accent-memory);
    font-size:var(--size-meta);
    line-height:var(--leading-body);
  }
  li.inferred { border-left-color:var(--text-muted); }
  li + li { margin-top:var(--space-2); }

  .content { min-width:0; overflow-wrap:anywhere; }

  .source {
    border:0; padding:0; color:var(--text-muted);
    transition:color var(--dur-fast) var(--ease-out);
  }
  .source:hover { background:none; color:var(--accent-memory); }

  .empty { margin:0; font-size:var(--size-meta); font-style:italic; color:var(--text-secondary); }

  .graph-scroll {
    overflow-x: auto;
    overflow-y: visible;
    margin-bottom: var(--space-3);
  }

  .graph {
    position: relative;
  }

  .lane-label {
    position: absolute;
    top: 0;
    transform: translateX(-50%);
    font-size: 0.7rem;
    font-family: var(--font-technical);
    color: var(--text-muted);
    white-space: nowrap;
  }

  .lane-line {
    position: absolute;
    width: 2px;
    transform: translateX(-1px);
    opacity: 0.4;
  }

  .node {
    position: absolute;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    transform: translate(-50%, -50%);
    border: 2px solid var(--surface-veil);
    padding: 0;
    cursor: pointer;
  }
  .node:hover { width: 13px; height: 13px; }
  .node.selected {
    outline: 2px solid var(--text-primary);
    outline-offset: 2px;
  }

  /* same hover-preview trick used for citation badges elsewhere in this app */
  .node {
    position: absolute;
  }
  .node::after {
    content: attr(data-preview);
    position: absolute;
    bottom: 100%;
    left: 50%;
    transform: translateX(-50%) translateY(-6px);
    width: max-content;
    max-width: 14rem;
    background: var(--surface-card);
    border: 0.5px solid var(--border-hairline);
    border-radius: var(--radius-sm);
    padding: 0.4rem 0.55rem;
    font-family: var(--font-technical);
    font-size: 0.68rem;
    line-height: 1.35;
    color: var(--text-secondary);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.12s ease;
    z-index: 20;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  }
  .node:hover::after { opacity: 1; }

  .detail-card {
    border: 0.5px solid var(--border-hairline);
    border-radius: var(--radius-sm);
    background: var(--surface-card);
    padding: var(--space-3);
    font-size: var(--size-meta);
  }
  .detail-header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-bottom: var(--space-2);
  }
  .detail-verb { font-weight: 600; }
  .branch-tag {
    color: var(--text-muted);
    font-size: 0.75em;
    padding: 0 0.4em;
    border: 0.5px solid var(--border-hairline);
    border-radius: var(--radius-sm);
  }
  .detail-header .icon-btn.small { margin-left: auto; }
  .detail-summary { margin-bottom: var(--space-2); }
  .detail-time { color: var(--text-muted); font-size: 0.8em; margin-bottom: var(--space-2); }
  .detail-changes {
    list-style: disc;
    padding-left: 1.2em;
    margin: 0 0 var(--space-2);
    font-family: var(--font-technical);
    font-size: 0.8em;
    color: var(--text-secondary);
  }
</style>