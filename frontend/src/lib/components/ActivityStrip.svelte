<script>
  import Collapsible from './Collapsible.svelte';
  import { reveal } from '$lib/motion.js';

  let { act } = $props();

  const KINDS = {
    memory_read:  { icon:'ti-notebook',      accent:'var(--accent-memory)' },
    memory_write: { icon:'ti-writing',       accent:'var(--accent-memory)' },
    skill:        { icon:'ti-pencil',        accent:'var(--accent-skill)' },
    searching:    { icon:'ti-radar',         accent:'var(--accent-search)' },
    search:       { icon:'ti-world-search',  accent:'var(--accent-search)' },
    search_failed:{ icon:'ti-plug-off',      accent:'var(--accent-attention)' }
  };

  const m = $derived(KINDS[act.kind] ?? { icon:'ti-point', accent:'var(--accent-skill)' });
</script>

{#if act.units?.length}
  <Collapsible label={act.label} icon={m.icon} accent={m.accent} count={act.units.length}>
    <ul class="units">
      {#each act.units as u}
        <li in:reveal>
          <span class={u.provenance === 'inferred' ? 'provenance-inferred' : 'provenance-stated'}>
            {u.content}
          </span>
          <span class="technical type">{u.unit_type}</span>
        </li>
      {/each}
    </ul>
  </Collapsible>
{:else if act.results?.length}
  <Collapsible label={act.label} icon={m.icon} accent={m.accent} count={act.results.length}>
    <ul class="results">
      {#each act.results as r}
        <li in:reveal>
          <a href={r.url} target="_blank" rel="noreferrer">{r.title}</a>
          <p class="summary">{r.summary}</p>
        </li>
      {/each}
    </ul>
  </Collapsible>
{:else}
  <p class="line" style="--accent:{m.accent}" class:pulsing={act.kind === 'searching'}>
    <i class="ti {m.icon}" aria-hidden="true"></i>{act.label}
  </p>
{/if}

<style>
  .line {
    display:flex; align-items:center; gap:var(--space-2); margin:0.4rem 0 0;
    font-size:var(--size-meta); color:var(--text-secondary);
  }
  .line i { font-size:15px; color:var(--accent); }
  .pulsing i { animation:breathe 1.6s var(--ease-inout) infinite; }
  @keyframes breathe { 0%,100% { opacity:.4 } 50% { opacity:1 } }
  .units, .results { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:var(--space-2); }
  .units li { font-size:var(--size-meta); line-height:var(--leading-tight); }
  .type { display:block; color:var(--text-muted); margin-top:2px; }
  .results a { color:var(--accent-search); font-size:var(--size-meta); }
  .results .summary { margin:2px 0 0; color:var(--text-secondary); font-size:var(--size-caption); }
</style>