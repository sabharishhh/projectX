<script>
  import { slide } from 'svelte/transition';
  import { settings, dur } from '$lib/motion.js';

  let {
    open = $bindable(false),
    label,
    count = null,
    accent = 'var(--accent-skill)',
    icon = null,
    boxed = true,
    actionIcon = null,
    actionLabel = '',
    onAction = null,
    children
  } = $props();

  const id = `c-${Math.random().toString(36).slice(2, 8)}`;
</script>

<div class="collapsible" class:boxed style="--accent:{accent}">
  <div class="trigger-row">
    <button
      class="trigger"
      aria-expanded={open}
      aria-controls={id}
      onclick={() => (open = !open)}
    >
      {#if icon}<i class="ti {icon}" aria-hidden="true"></i>{/if}
      <span class="label">{label}</span>
      {#if count !== null}<span class="count technical">{count}</span>{/if}
      <svg class="chevron" class:open viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
        <path d="M3 4.5 6 7.5 9 4.5" fill="none" stroke="currentColor" stroke-width="1.4"
              stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>
    {#if onAction}
      <button class="action" title={actionLabel} aria-label={actionLabel} onclick={onAction}>
        <i class="ti {actionIcon}" aria-hidden="true"></i>
      </button>
    {/if}
  </div>

  {#if open}
    <div {id} class="body" transition:slide={{ duration: dur(settings.base), easing: settings.ease }}>
      {@render children?.()}
    </div>
  {/if}
</div>

<style>
  .collapsible.boxed {
    margin-top: var(--space-2);
    border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent);
    background: color-mix(in srgb, var(--accent) 6%, transparent);
    border-radius: var(--radius-sm, 4px);
  }
  .collapsible.boxed .trigger-row { padding: var(--space-2) var(--space-3); }
  .collapsible.boxed .body { padding: 0 var(--space-3) var(--space-3); }

  .trigger-row { display: flex; align-items: center; gap: var(--space-1); }

  .trigger {
    display:flex; align-items:center; gap:var(--space-2);
    flex: 1; min-width: 0;
    border:0; background:none; cursor:pointer;
    padding: var(--space-2) 0;
    font-size:var(--size-meta); color:var(--text-secondary); text-align:left;
  }
  .trigger:hover { color:var(--text-primary); }
  .trigger:hover .chevron { opacity:1; }
  .trigger i { font-size:15px; color:var(--accent); }
  .label { flex:1; font-weight:var(--weight-medium); letter-spacing:0.01em; }
  .count { color:var(--text-muted); }
  .chevron {
    opacity:.5; color:var(--text-muted);
    transition:transform var(--dur-fast) var(--ease-out), opacity var(--dur-fast) var(--ease-out);
  }
  .chevron.open { transform:rotate(180deg); }

  .action {
    flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    width: 1.6rem; height: 1.6rem;
    border: none; background: transparent;
    color: var(--text-muted);
    border-radius: var(--radius-sm, 4px);
    cursor: pointer;
  }
  .action:hover { color: var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); }
  .action i { font-size: 13px; }

  .body { padding: 0; }
</style>