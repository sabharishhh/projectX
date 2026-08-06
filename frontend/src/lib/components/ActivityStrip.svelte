<script>
    import Collapsible from './Collapsible.svelte';
  import { reveal } from '$lib/motion.js';
  import { KINDS } from './activityKinds.js';

  let { act, chatId, nested = false } = $props();
  import { openMemoryPanelForChat } from '../stores/workspace.svelte.ts';

  const m = $derived(KINDS[act.kind] ?? { icon:'ti-point', accent:'var(--accent-primary)' });
  const active = $derived(act.kind === 'searching' || act.kind === 'skill');
</script>

<div class="trace-row" in:reveal style="--accent:{m.accent}">
  <span class="node" class:pulsing={active}>
    <i class="ti {m.icon}" aria-hidden="true"></i>
  </span>

  <div class="trace-content">
    {#if act.units?.length}
      {#if nested}
        <p class="line">{act.label}</p>
        <ul class="units">
          {#each act.units as u}
            <li in:reveal>
              <span class={u.provenance === 'inferred' ? 'provenance-inferred' : 'provenance-stated'}>
                {u.content}
              </span>
              {#if u.unit_type === 'commitment' && u.commitment_status && u.commitment_status !== 'open'}
                <span class="technical type status-{u.commitment_status}">{u.commitment_status}</span>
              {:else if u.deadline}
                <span class="technical type">due {new Date(u.deadline).toLocaleDateString()}</span>
              {:else}
                <span class="technical type">{u.unit_type}</span>
              {/if}
            </li>
          {/each}
        </ul>
      {:else}
        <Collapsible
          label={act.label} count={act.units.length} accent={m.accent}
          actionIcon="ti-arrow-up-right" actionLabel="View in memory panel"
          onAction={() => openMemoryPanelForChat(chatId)}
        >
          <ul class="units">
            {#each act.units as u}
              <li in:reveal>
                <span class={u.provenance === 'inferred' ? 'provenance-inferred' : 'provenance-stated'}>
                  {u.content}
                </span>
                {#if u.unit_type === 'commitment' && u.commitment_status && u.commitment_status !== 'open'}
                  <span class="technical type status-{u.commitment_status}">{u.commitment_status}</span>
                {:else if u.deadline}
                  <span class="technical type">due {new Date(u.deadline).toLocaleDateString()}</span>
                {:else}
                  <span class="technical type">{u.unit_type}</span>
                {/if}
              </li>
            {/each}
          </ul>
        </Collapsible>
      {/if}
    {:else if act.results?.length}
      {#if nested}
        <p class="line">{act.label}</p>
        <ul class="results">
          {#each act.results as r}
            <li in:reveal>
              <a href={r.url} target="_blank" rel="noreferrer">{r.title}</a>
              <p class="summary">{r.summary}</p>
            </li>
          {/each}
        </ul>
      {:else}
        <Collapsible label={act.label} count={act.results.length} accent={m.accent}>
          <ul class="results">
            {#each act.results as r}
              <li in:reveal>
                <a href={r.url} target="_blank" rel="noreferrer">{r.title}</a>
                <p class="summary">{r.summary}</p>
              </li>
            {/each}
          </ul>
        </Collapsible>
      {/if}
    {:else if act.steps?.length}
      {#if nested}
        <p class="line">{act.label}</p>
        <ul class="steps">
          {#each act.steps as step}
            <li in:reveal>{step}</li>
          {/each}
        </ul>
      {:else}
        <Collapsible label={act.label} count={act.steps.length} accent={m.accent}>
          <ul class="steps">
            {#each act.steps as step}
              <li in:reveal>{step}</li>
            {/each}
          </ul>
        </Collapsible>
      {/if}
    {:else}
      <p class="line" class:completed={!active}>{act.label}</p>
    {/if}
  </div>
</div>

<style>
  .trace-row {
    display: flex;
    align-items: flex-start;
    gap: var(--space-3);
    margin: var(--space-2) 0 0;
  }
  .node {
    flex-shrink: 0;
    width: 22px; height: 22px;
    margin-top: 1px;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    background: color-mix(in srgb, var(--accent) 14%, transparent);
    color: var(--accent);
  }
  .node i { font-size: 12px; }
  .node.pulsing { animation: node-breathe 2.2s var(--ease-inout) infinite; }
  @keyframes node-breathe {
    0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 30%, transparent); }
    50%      { box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 0%, transparent); }
  }
  .trace-content { flex: 1; min-width: 0; padding-top: 2px; }
  .trace-content :global(.collapsible) { margin-top: 0 !important; }
  .line {
    margin: 0;
    font-size: var(--size-meta);
    color: var(--text-secondary);
  }
  .line.completed { color: var(--text-muted); }
  .units, .results, .steps { list-style:none; margin:var(--space-1) 0 0; padding:0; display:flex; flex-direction:column; gap:var(--space-2); }
  .units li { font-size:var(--size-meta); line-height:var(--leading-tight); }
  .units li span:first-child { text-decoration: none; }
  .type { display:block; color:var(--text-muted); margin-top:2px; }
  .status-done { color: var(--accent-primary); }
  .status-cancelled { color: var(--text-muted); }
  .results a { color:var(--accent-primary-soft); font-size:var(--size-meta); }
  .results .summary { margin:2px 0 0; color:var(--text-secondary); font-size:var(--size-caption); }
  .steps li { font-size:var(--size-meta); color:var(--text-secondary); line-height:var(--leading-tight); }
</style>