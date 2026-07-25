<script>
  import Collapsible from './Collapsible.svelte';
  import { reveal } from '$lib/motion.js';

  let { events = [] } = $props();

  const KINDS = {
    memory_read:  { icon:'ti-notebook',      accent:'var(--accent-memory)' },
    memory_write: { icon:'ti-writing',       accent:'var(--accent-memory)' },
    skill:        { icon:'ti-pencil',        accent:'var(--accent-skill)' },
    searching:    { icon:'ti-radar',         accent:'var(--accent-search)' },
    search:       { icon:'ti-world-search',  accent:'var(--accent-search)' },
    search_failed:{ icon:'ti-plug-off',      accent:'var(--accent-attention)' }
  };

  const meta = (k) => KINDS[k] ?? { icon:'ti-point', accent:'var(--accent-skill)' };
  const inFlight = $derived(events.some((e) => e.kind === 'searching'));
</script>

<aside class="rail" aria-label="What happened this turn">
  {#each events as event (event.label)}
    {@const m = meta(event.kind)}
    {#if event.units?.length}
      <Collapsible label={event.label} icon={m.icon} accent={m.accent} count={event.units.length}>
        <ul class="units">
          {#each event.units as u}
            <li in:reveal>
              <span class={u.provenance === 'inferred' ? 'provenance-inferred' : 'provenance-stated'}>
                {u.content}
              </span>
              <span class="technical type">{u.unit_type}</span>
            </li>
          {/each}
        </ul>
      </Collapsible>
    {:else}
      <p class="line" style="--accent:{m.accent}" class:pulsing={event.kind === 'searching' && inFlight}>
        <i class="ti {m.icon}" aria-hidden="true"></i>{event.label}
      </p>
    {/if}
  {/each}
</aside>

<style>
  .rail { width:var(--rail-width); display:flex; flex-direction:column; gap:var(--space-1); }
  .line {
    display:flex; align-items:center; gap:var(--space-2); margin:0;
    padding:var(--space-2) 0; font-size:var(--size-meta); color:var(--text-secondary);
  }
  .line i { font-size:15px; color:var(--accent); }
  .pulsing i { animation:breathe 1.6s var(--ease-inout) infinite; }
  @keyframes breathe { 0%,100% { opacity:.4 } 50% { opacity:1 } }
  .units { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:var(--space-2); }
  .units li { font-size:var(--size-meta); line-height:var(--leading-tight); }
  .type { display:block; color:var(--text-muted); margin-top:2px; }
  @media (max-width:900px) {
    .rail { width:100%; border-top:0.5px solid var(--border-hairline); padding-top:var(--space-2); }
  }
</style>