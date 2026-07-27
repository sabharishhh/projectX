<script>
  import Collapsible from './Collapsible.svelte';
  import { reveal } from '$lib/motion.js';

  let { memory = [], onopensource = () => {}, onToggle } = $props();

  const ORDER = ['identity', 'preference', 'project', 'decision', 'relationship'];
  const grouped = $derived(
    ORDER.map((type) => ({ type, items: memory.filter((u) => u.unit_type === type) }))
         .filter((g) => g.items.length)
  );
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
  
  .icon-btn svg {
    width: 1.25rem;
    height: 1.25rem;
    flex-shrink: 0;
  }
  
  .icon-btn:hover {
    background: var(--surface-sunken);
    color: var(--text-primary);
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
</style>