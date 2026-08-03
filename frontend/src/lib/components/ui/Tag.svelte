<script>
  let { type = 'gray', size = 'default', children } = $props();
</script>

<span class="tag type-{type} size-{size}">{@render children?.()}</span>

<style>
  .tag {
    display: inline-flex; align-items: center;
    font-family: var(--font-technical); border-radius: 999px; white-space: nowrap;
  }
  .size-default { padding: 2px 10px; font-size: var(--size-caption); }
  .size-sm { padding: 1px 8px; font-size: 11px; }
  .type-blue { background: color-mix(in srgb, var(--accent-primary) 20%, transparent); color: var(--accent-primary); }
  .type-warm-gray { background: var(--surface-raised); color: var(--text-secondary); }
  .type-cool-gray { background: var(--surface-sunken); color: var(--text-muted); }
  .type-gray { background: var(--surface-sunken); color: var(--text-secondary); }
</style>