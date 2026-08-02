<script>
  import Collapsible from './Collapsible.svelte';
  import { reveal } from '$lib/motion.js';

  let { memory = [], history = [], onopensource = () => {}, ondelete = () => {}, onedit = () => {}, oncreate = () => {}, onToggle } = $props();

  let view = $state('current'); // 'current' | 'timeline'
  let selectedEntry = $state(null);
  let hoveredHash = $state(null);
  let tooltipAlign = $state('center'); // 'center' | 'left' | 'right'
  let editingHash = $state(null);
  let editDraft = $state('');
  let showAddCommitment = $state(false);
  let newCommitmentText = $state('');
  let newCommitmentDeadline = $state('');

  const ORDER = ['identity', 'preference', 'project', 'decision', 'relationship', 'commitment', 'correction'];
  const grouped = $derived(
    ORDER.map((type) => ({
      type,
      items: memory.filter((u) =>
        u.unit_type === type &&
        !(type === 'commitment' && u.commitment_status && u.commitment_status !== 'open')
      ),
    })).filter((g) => g.items.length || g.type === 'commitment')
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

  function startEdit(u) {
    editingHash = u.hash;
    editDraft = u.content;
  }

  function cancelEdit() {
    editingHash = null;
    editDraft = '';
  }

  function saveEdit(u) {
    const trimmed = editDraft.trim();
    if (trimmed && trimmed !== u.content) {
      onedit(u, trimmed);
    }
    editingHash = null;
    editDraft = '';
  }

  function submitNewCommitment() {
    const trimmed = newCommitmentText.trim();
    if (!trimmed) return;
    oncreate(trimmed, newCommitmentDeadline || null);
    newCommitmentText = '';
    newCommitmentDeadline = '';
    showAddCommitment = false;
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

  function handleNodeHover(event, hash) {
    hoveredHash = hash;
    const nodeRect = event.currentTarget.getBoundingClientRect();
    const container = event.currentTarget.closest('.graph-scroll');
    const containerRect = container.getBoundingClientRect();
    const tooltipHalfWidth = 120;

    if (nodeRect.left - tooltipHalfWidth < containerRect.left) {
      tooltipAlign = 'left';
    } else if (nodeRect.right + tooltipHalfWidth > containerRect.right) {
      tooltipAlign = 'right';
    } else {
      tooltipAlign = 'center';
    }
  }

  function handleNodeLeave() {
    hoveredHash = null;
  }
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
                {#if editingHash === u.hash}
                  <div class="edit-row">
                    <textarea
                      class="edit-input"
                      bind:value={editDraft}
                      rows="2"
                      onkeydown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEdit(u); }
                        if (e.key === 'Escape') cancelEdit();
                      }}
                    ></textarea>
                    <div class="edit-actions">
                      <button class="edit-save" onclick={() => saveEdit(u)}>Save</button>
                      <button class="edit-cancel" onclick={cancelEdit}>Cancel</button>
                    </div>
                  </div>
                {:else}
                  <span
                    class="content {u.provenance === 'inferred' ? 'provenance-inferred' : 'provenance-stated'}"
                  >
                    {u.content}
                  </span>
                  <span class="item-actions">
                    {#if u.deadline}
                      <span class="technical type">due {new Date(u.deadline).toLocaleDateString()}</span>
                    {:else}
                      <button class="source technical" title={u.source} onclick={() => onopensource(u.source)}>
                        {u.hash.slice(0, 8)}
                      </button>
                    {/if}
                    <button class="mini-btn" title="Edit" aria-label="Edit" onclick={() => startEdit(u)}>✎</button>
                    <button class="mini-btn danger" title="Delete" aria-label="Delete" onclick={() => ondelete(u)}>×</button>
                  </span>
                {/if}
              </li>
            {/each}
          </ul>

          {#if group.type === 'commitment'}
            <div class="add-commitment">
              {#if showAddCommitment}
                <input type="text" class="add-input" placeholder="What do you need to do?" bind:value={newCommitmentText} />
                <input type="date" class="add-date" bind:value={newCommitmentDeadline} title="Leave blank for no due date — stays as a passive reminder" />
                <div class="edit-actions">
                  <button class="edit-save" onclick={submitNewCommitment}>Add</button>
                  <button class="edit-cancel" onclick={() => (showAddCommitment = false)}>Cancel</button>
                </div>
              {:else}
                <button class="mini-btn" onclick={() => (showAddCommitment = true)}>+ Add commitment</button>
              {/if}
            </div>
          {/if}
        </Collapsible>
      </div>
    {/each}
  {:else}
    {#if history.length === 0}
      <p class="empty">No history yet.</p>
    {:else}
      <p class="graph-note">
        Each column is a branch, arranged by time. Branches don't currently
        record where they forked from — this shows parallel history, not
        merges between them.
      </p>

      <div class="graph-legend">
        <span class="legend-item"><span class="legend-shape circle"></span> fact</span>
        <span class="legend-item"><span class="legend-shape diamond"></span> commitment</span>
      </div>

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
              class:commitment={isCommitment(entry)}
              class:selected={selectedEntry?.hash === entry.hash}
              class:align-left={hoveredHash === entry.hash && tooltipAlign === 'left'}
              class:align-right={hoveredHash === entry.hash && tooltipAlign === 'right'}
              style="left:{laneX(entry.branch)}px; top:{LABEL_HEIGHT + i * ROW_HEIGHT + ROW_HEIGHT / 2}px; background:{branchColor(entry.branch)}"
              data-preview="{commitVerb(entry)} — {entry.summary}"
              onmouseenter={(e) => handleNodeHover(e, entry.hash)}
              onmouseleave={handleNodeLeave}
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
            {#if isCommitment(selectedEntry)}
              <span class="type-tag">commitment</span>
            {/if}
            <span class="branch-tag">{selectedEntry.branch}</span>
            <button class="icon-btn small" onclick={() => (selectedEntry = null)} aria-label="Close">×</button>
          </div>
          <div class="detail-summary">{selectedEntry.summary}</div>
          <div class="detail-time">{new Date(selectedEntry.created_at).toLocaleString()}</div>
          <ul class="detail-changes">
            {#each selectedEntry.changes as change, i (i)}
              <li>
                {verb(change)}{change.kind === 'modified' ? ` (${change.from.slice(0,8)} → ${change.to.slice(0,8)})` : ` (${change.hash.slice(0,8)})`}
                {#if change.unit_type} — {change.unit_type}{/if}
              </li>
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

  .item-actions {
    display: flex;
    align-items: center;
    gap: 0.3rem;
    flex-shrink: 0;
  }

  .source {
    border:0; padding:0; color:var(--text-muted);
    transition:color var(--dur-fast) var(--ease-out);
  }
  .source:hover { background:none; color:var(--accent-memory); }

  .mini-btn {
    border: 0;
    padding: 0.1rem 0.35rem;
    background: none;
    color: var(--text-muted);
    border-radius: var(--radius-sm);
    cursor: pointer;
    font-size: 0.85em;
    line-height: 1;
  }
  .mini-btn:hover { background: var(--surface-sunken); color: var(--text-primary); }
  .mini-btn.danger:hover { color: var(--text-danger); background: var(--bg-danger); }

  .edit-row {
    grid-column: 1 / -1;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .edit-input {
    width: 100%;
    box-sizing: border-box;
    font-family: inherit;
    font-size: var(--size-meta);
    padding: 0.4rem 0.5rem;
    border: 0.5px solid var(--accent-memory);
    border-radius: var(--radius-sm);
    background: var(--surface-page);
    color: var(--text-primary);
    resize: vertical;
  }
  .edit-actions { display: flex; gap: 0.4rem; }
  .edit-save, .edit-cancel {
    font-size: 0.75rem;
    padding: 0.25rem 0.6rem;
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .edit-save {
    border: none;
    background: var(--accent-memory);
    color: var(--surface-page);
  }
  .edit-cancel {
    border: 0.5px solid var(--border-hairline);
    background: none;
    color: var(--text-secondary);
  }

  .empty { margin:0; font-size:var(--size-meta); font-style:italic; color:var(--text-secondary); }

  .graph-note {
    margin: 0 0 var(--space-2);
    font-size: 0.75rem;
    color: var(--text-muted);
    font-style: italic;
    line-height: 1.4;
  }

  .graph-legend {
    display: flex;
    gap: var(--space-3);
    margin-bottom: var(--space-3);
    font-size: 0.75rem;
    color: var(--text-secondary);
  }
  .legend-item { display: flex; align-items: center; gap: 0.35em; }
  .legend-shape {
    width: 9px; height: 9px;
    background: var(--text-muted);
    display: inline-block;
  }
  .legend-shape.circle { border-radius: 50%; }
  .legend-shape.diamond { border-radius: 2px; transform: rotate(45deg); }

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

  .node.commitment {
    border-radius: 0;
    clip-path: polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%);
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

  .node.align-left::after {
    left: 0;
    transform: translateY(-6px);
  }
  .node.align-right::after {
    left: auto;
    right: 0;
    transform: translateY(-6px);
  }

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
  .type-tag, .branch-tag {
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
  .add-commitment {
    margin-top: var(--space-2);
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .add-input, .add-date {
    width: 100%;
    box-sizing: border-box;
    font-family: inherit;
    font-size: var(--size-meta);
    padding: 0.4rem 0.5rem;
    border: 0.5px solid var(--border-hairline);
    border-radius: var(--radius-sm);
    background: var(--surface-page);
    color: var(--text-primary);
  }
  .add-input:focus, .add-date:focus {
    border-color: var(--accent-memory);
    outline: none;
  }
</style>