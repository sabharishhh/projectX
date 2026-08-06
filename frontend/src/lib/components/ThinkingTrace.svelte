<script>
  import { onDestroy } from 'svelte';
  import { reveal } from '../motion.js';
  import { KINDS } from './activityKinds.js';

  let { activity = [], startedAt = null, settledAt = null } = $props();

  let open = $state(false);

  const settled = $derived(settledAt != null);
  const isLive = $derived(startedAt != null && !settled);

  // Elapsed time needs to actually tick during the live phase, not just
  // be computed once — Date.now() alone inside a $derived only
  // re-evaluates when one of ITS OWN reactive dependencies changes, and
  // Date.now() isn't reactive on its own. `now` is a real ticking clock,
  // advanced every second only while live, so the counter genuinely
  // increments in front of the user instead of appearing frozen until
  // settlement.
  let now = $state(Date.now());
  let ticker = null;

  $effect(() => {
    if (isLive) {
      ticker = setInterval(() => { now = Date.now(); }, 1000);
      return () => clearInterval(ticker);
    }
  });

  onDestroy(() => { if (ticker) clearInterval(ticker); });

  const elapsedSeconds = $derived(
    startedAt ? Math.max(1, Math.round(((settledAt ?? now) - startedAt) / 1000)) : null
  );

  const liveLabel = $derived(activity.length ? activity[activity.length - 1].label : 'Thinking…');

  const counts = $derived.by(() => {
    const c = {};
    for (const act of activity) {
      if (act.units?.length) c.facts = (c.facts || 0) + act.units.length;
      else if (act.results?.length) c.sources = (c.sources || 0) + act.results.length;
      else if (act.steps?.length) c.searches = (c.searches || 0) + act.steps.length;
    }
    return c;
  });

  const summary = $derived(
    [
      counts.facts ? `${counts.facts} fact${counts.facts === 1 ? '' : 's'}` : null,
      counts.sources ? `${counts.sources} source${counts.sources === 1 ? '' : 's'}` : null,
      counts.searches ? `${counts.searches} search${counts.searches === 1 ? '' : 'es'}` : null,
    ].filter(Boolean).join(' · ')
  );

  function iconFor(kind) {
    return KINDS[kind]?.icon ?? 'ti-point';
  }

  const MAX_SHOWN = 6;
  function capped(list) {
    return { shown: list.slice(0, MAX_SHOWN), remaining: Math.max(0, list.length - MAX_SHOWN) };
  }
</script>

{#if activity.length || isLive}
  <div class="trace">
    <button class="trace-trigger" onclick={() => (open = !open)} aria-expanded={open}>
      <span class="dot" class:pulsing={!settled}></span>
      <span class="trace-label">
        {#if !settled}
          Working for {elapsedSeconds}s{activity.length ? ` · ${liveLabel}` : ''}
        {:else}
          Worked for {elapsedSeconds}s{summary ? ` · ${summary}` : ''}
        {/if}
      </span>
      <svg class="chevron" class:open viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
        <path d="M3 4.5 6 7.5 9 4.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>

    {#if open}
      <div class="trace-detail" transition:reveal={{ duration: 180 }}>
        {#each activity as act}
          {#if act.kind === 'reasoning'}
            <p class="trace-line reasoning">
              <i class="ti {iconFor(act.kind)}" aria-hidden="true"></i>
              <span>{act.label}</span>
            </p>
          {:else if act.units?.length}
            {@const { shown, remaining } = capped(act.units)}
            <div class="trace-group">
              <p class="trace-group-label"><i class="ti {iconFor(act.kind)}" aria-hidden="true"></i> {act.label}</p>
              {#each shown as u}
                <p class="trace-line indent">
                  {u.content}
                  {#if u.unit_type === 'commitment' && u.commitment_status && u.commitment_status !== 'open'}
                    <span class="muted">— {u.commitment_status}</span>
                  {:else if u.deadline}
                    <span class="muted">— due {new Date(u.deadline).toLocaleDateString()}</span>
                  {/if}
                </p>
              {/each}
              {#if remaining > 0}
                <p class="trace-line indent more">+{remaining} more</p>
              {/if}
            </div>
          {:else if act.results?.length}
            {@const { shown, remaining } = capped(act.results)}
            <div class="trace-group">
              <p class="trace-group-label"><i class="ti {iconFor(act.kind)}" aria-hidden="true"></i> {act.label}</p>
              {#each shown as r}
                <p class="trace-line indent"><a href={r.url} target="_blank" rel="noreferrer">{r.title}</a></p>
              {/each}
              {#if remaining > 0}
                <p class="trace-line indent more">+{remaining} more — see Sources panel</p>
              {/if}
            </div>
          {:else if act.steps?.length}
            {@const { shown, remaining } = capped(act.steps)}
            <div class="trace-group">
              <p class="trace-group-label"><i class="ti {iconFor(act.kind)}" aria-hidden="true"></i> {act.label}</p>
              {#each shown as step}
                <p class="trace-line indent">{step}</p>
              {/each}
              {#if remaining > 0}
                <p class="trace-line indent more">+{remaining} more</p>
              {/if}
            </div>
          {:else}
            <p class="trace-line">
              <i class="ti {iconFor(act.kind)}" aria-hidden="true"></i>
              <span>{act.label}</span>
            </p>
          {/if}
        {/each}
        {#if isLive && !activity.length}
          <p class="trace-line muted-line">Nothing to show yet…</p>
        {/if}
      </div>
    {/if}
  </div>
{/if}

<style>
  .trace { margin: 0 0 var(--space-4); }

  .trace-trigger {
    display: flex; align-items: center; gap: var(--space-2);
    background: none; border: none; padding: 0;
    cursor: pointer;
    color: var(--text-muted);
    font-size: var(--size-caption);
  }
  .trace-trigger:hover { color: var(--text-secondary); }
  .trace-trigger:hover .chevron { opacity: 1; }

  .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--text-muted); flex-shrink: 0; }
  .dot.pulsing { background: var(--accent-primary); animation: dot-pulse 1.4s ease-in-out infinite; }
  @keyframes dot-pulse { 0%, 100% { opacity: 0.4; } 50% { opacity: 1; } }

  .trace-label { line-height: 1.4; }

  .chevron { opacity: 0.5; transition: transform var(--dur-fast) var(--ease-out), opacity var(--dur-fast) var(--ease-out); }
  .chevron.open { transform: rotate(180deg); }

  .trace-detail {
    margin-top: var(--space-2);
    padding-left: calc(6px + var(--space-2));
    display: flex; flex-direction: column; gap: var(--space-3);
  }

  .trace-group { display: flex; flex-direction: column; gap: 2px; }
  .trace-group-label {
    margin: 0; display: flex; align-items: center; gap: 6px;
    font-size: var(--size-caption); font-weight: var(--weight-medium);
    color: var(--text-secondary);
  }
  .trace-group-label i { font-size: 11px; color: var(--accent-primary); flex-shrink: 0; }

  .trace-line {
    margin: 0; display: flex; align-items: baseline; gap: 6px;
    font-size: var(--size-caption); color: var(--text-secondary); line-height: 1.5;
  }
  .trace-line i { font-size: 11px; color: var(--text-muted); flex-shrink: 0; }
  .trace-line.indent { padding-left: 17px; color: var(--text-muted); }
  .trace-line a { color: var(--accent-primary-soft); }
  .trace-line .muted { color: var(--text-muted); }
  .trace-line.more { font-style: italic; opacity: 0.75; }
  .trace-line.muted-line { font-style: italic; color: var(--text-muted); }

  .trace-line.reasoning span {
    font-style: italic;
    color: var(--text-muted);
  }
  .trace-line.reasoning i { color: var(--accent-attention); }
</style>