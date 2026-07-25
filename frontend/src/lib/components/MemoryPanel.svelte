<script>
  import Collapsible from './Collapsible.svelte';
  import { reveal } from '$lib/motion.js';

  let { memory = [], onopensource = () => {} } = $props();

  const ORDER = ['identity', 'preference', 'project', 'decision', 'relationship'];
  const grouped = $derived(
    ORDER.map((type) => ({ type, items: memory.filter((u) => u.unit_type === type) }))
         .filter((g) => g.items.length)
  );
</script>

<div class="panel">
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