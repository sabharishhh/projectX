<script>
  import Collapsible from './Collapsible.svelte';
  import { reveal } from '$lib/motion.js';

  let { units = [], onopensource } = $props();

  const ORDER = ['identity', 'preference', 'project', 'decision', 'relationship'];
  const grouped = $derived(
    ORDER.map((type) => ({ type, items: units.filter((u) => u.unit_type === type) }))
         .filter((g) => g.items.length)
  );
</script>

<div class="panel">
  {#each grouped as group (group.type)}
    <Collapsible
      label={group.type}
      count={group.items.length}
      accent="var(--accent-memory)"
      open={group.type === 'identity'}
    >
      <ul>
        {#each group.items as u (u.hash)}
          <li in:reveal>
            <span class={u.provenance === 'inferred' ? 'provenance-inferred' : 'provenance-stated'}>
              {u.content}
            </span>
            <button class="source technical" onclick={() => onopensource(u.source)}>
              {u.hash.slice(0, 8)}
            </button>
          </li>
        {/each}
      </ul>
    </Collapsible>
  {/each}
</div>

<style>
  .panel { display:flex; flex-direction:column; }
  ul { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:var(--space-3); }
  li { display:flex; justify-content:space-between; gap:var(--space-3); align-items:baseline; font-size:var(--size-meta); }
  .source {
    border:0; padding:0; color:var(--text-muted);
    transition:color var(--dur-fast) var(--ease-out);
  }
  .source:hover { background:none; color:var(--accent-memory); }
</style>