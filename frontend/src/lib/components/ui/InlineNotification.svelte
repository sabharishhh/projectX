<script>
  let { kind = 'error', title = '', subtitle = '' } = $props();
  const COLORS = { error: 'var(--danger)', warning: 'var(--amber)', success: 'var(--accent-primary)', info: 'var(--accent-primary)' };
  const accent = $derived(COLORS[kind] ?? 'var(--accent-primary)');
</script>

<div class="notification" style="--accent:{accent}" role="alert">
  <span class="bar"></span>
  <div class="body">
    {#if title}<p class="title">{title}</p>{/if}
    {#if subtitle}<p class="subtitle">{subtitle}</p>{/if}
  </div>
</div>

<style>
  .notification { display: flex; gap: var(--space-3); background: color-mix(in srgb, var(--accent) 8%, var(--surface-card)); border-radius: var(--radius-sm); padding: var(--space-3); margin-top: var(--space-2); }
  .bar { flex-shrink: 0; width: 3px; border-radius: 2px; background: var(--accent); }
  .body { min-width: 0; }
  .title { margin: 0; font-size: var(--size-meta); font-weight: var(--weight-semibold); color: var(--text-primary); }
  .subtitle { margin: 2px 0 0; font-size: var(--size-meta); color: var(--text-secondary); word-break: break-word; }
</style>