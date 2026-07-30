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
    search_failed:{ icon:'ti-plug-off',      accent:'var(--accent-attention)' },
    tool_group:   { icon:'ti-world-search',  accent:'var(--accent-search)' }
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
          {#if u.deadline}
            <span class="technical type">due {new Date(u.deadline).toLocaleDateString()}</span>
          {:else}
            <span class="technical type">{u.unit_type}</span>
          {/if}
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
{:else if act.steps?.length}
  <Collapsible label={act.label} icon={m.icon} accent={m.accent} count={act.steps.length}>
    <ul class="steps">
      {#each act.steps as step}
        <li in:reveal>{step}</li>
      {/each}
    </ul>
  </Collapsible>
{:else}
  <p 
    class="line" 
    style="--accent:{m.accent}" 
    class:pulsing={act.kind === 'searching' || act.kind === 'skill'} 
    class:completed={act.kind !== 'searching' && act.kind !== 'skill'}
  >
    <i class="ti {m.icon}" aria-hidden="true"></i>{act.label}
  </p>
{/if}

<style>
  .line {
    display:flex; align-items:center; gap:var(--space-2); margin:0.4rem 0 0;
    font-size:var(--size-meta); color:var(--text-secondary);
  }
  .line i { font-size:15px; color:var(--accent); }
  
  /* Dimmed, italic style for completed actions */
  .line.completed { 
    color: var(--text-muted); 
    font-style: italic; 
  }

  /* Animated gradient for active searching */
  .pulsing {
    background: linear-gradient(
      90deg,
      var(--text-muted) 0%,
      var(--text-muted) 45%,
      var(--text-primary) 50%, /* Swapped from var(--accent) to bright text color */
      var(--text-muted) 55%,
      var(--text-muted) 100%
    );
    background-size: 300% 100%;
    color: transparent;
    -webkit-background-clip: text;
    background-clip: text;
    animation: shine 3s linear infinite;
  }

  .pulsing i { 
    /* This keeps the icon itself the accent color (blue) */
    color: var(--accent); 
    animation: breathe 3s var(--ease-inout) infinite; 
  }

  @keyframes shine {
    0% { background-position: 100% center; }
    100% { background-position: -100% center; }
  }

  @keyframes breathe { 
    0%, 100% { opacity: 0.5; } 
    50% { opacity: 1; } 
  }

  .units, .results, .steps { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:var(--space-2); }
  .units li { font-size:var(--size-meta); line-height:var(--leading-tight); }
  .type { display:block; color:var(--text-muted); margin-top:2px; }
  .results a { color:var(--accent-search); font-size:var(--size-meta); }
  .results .summary { margin:2px 0 0; color:var(--text-secondary); font-size:var(--size-caption); }
  .steps li { font-size:var(--size-meta); color:var(--text-secondary); line-height:var(--leading-tight); }
</style>