<script>
  import { slide } from 'svelte/transition';
  import { settings, dur } from '$lib/motion.js';

  let {
    open = $bindable(false),
    label,
    count = null,
    accent = 'var(--accent-skill)',
    icon = null,
    children
  } = $props();

  const id = `c-${Math.random().toString(36).slice(2, 8)}`;
</script>

<div class="collapsible">
  <button
    class="trigger"
    aria-expanded={open}
    aria-controls={id}
    onclick={() => (open = !open)}
    style="--accent:{accent}"
  >
    {#if icon}<i class="ti {icon}" aria-hidden="true"></i>{/if}
    <span class="label">{label}</span>
    {#if count !== null}<span class="count technical">{count}</span>{/if}
    <svg class="chevron" class:open viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
      <path d="M3 4.5 6 7.5 9 4.5" fill="none" stroke="currentColor" stroke-width="1.4"
            stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  </button>

  {#if open}
    <div {id} class="body" transition:slide={{ duration: dur(settings.base), easing: settings.ease }}>
      {@render children?.()}
    </div>
  {/if}
</div>

<style>
  .trigger {
    display:flex; align-items:center; gap:var(--space-2);
    width:100%; border:0; padding:var(--space-2) 0;
    font-size:var(--size-meta); color:var(--text-secondary); text-align:left;
  }
  .trigger:hover { background:none; color:var(--text-primary); }
  .trigger:hover .chevron { opacity:1; }
  .trigger i { font-size:15px; color:var(--accent); }
  .label { flex:1; }
  .count { color:var(--text-muted); }
  .chevron {
    opacity:.5; color:var(--text-muted);
    transition:transform var(--dur-fast) var(--ease-out), opacity var(--dur-fast) var(--ease-out);
  }
  .chevron.open { transform:rotate(180deg); }
  .body { padding-block:var(--space-1) var(--space-3); }
</style>