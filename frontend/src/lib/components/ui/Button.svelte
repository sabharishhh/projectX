<script>
  let { kind = 'primary', size = 'default', disabled = false, icon = null, iconDescription = '', type = 'button', onclick = () => {}, children } = $props();
  const iconOnly = $derived(!!icon && !children);
</script>

<button
  {type}
  class="btn kind-{kind} size-{size}"
  class:icon-only={iconOnly}
  {disabled}
  title={iconOnly ? iconDescription : undefined}
  aria-label={iconOnly ? iconDescription : undefined}
  onclick={(e) => !disabled && onclick(e)}
>
  {#if icon}
    {@const Icon = icon}
    <Icon size={16} />
  {/if}
  {#if children}<span class="label">{@render children()}</span>{/if}
</button>

<style>
  .btn {
    display: inline-flex; align-items: center; justify-content: center; gap: var(--space-2);
    font-family: var(--font-voice); font-size: var(--size-meta); font-weight: var(--weight-medium);
    border: 1px solid transparent; border-radius: var(--radius-sm);
    cursor: pointer; white-space: nowrap;
    transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
  }
  .btn:disabled { opacity: 0.4; cursor: default; pointer-events: none; }
  .btn:focus-visible { outline: 2px solid var(--accent-primary); outline-offset: 2px; }

  .size-small { height: 2rem; padding: 0 var(--space-3); }
  .size-default, .size-field { height: 2.5rem; padding: 0 var(--space-4); }
  .icon-only.size-small { width: 2rem; padding: 0; }
  .icon-only.size-default, .icon-only.size-field { width: 2.5rem; padding: 0; }

  .kind-primary { background: var(--accent-primary); color: var(--text-on-accent); }
  .kind-primary:hover:not(:disabled) { background: color-mix(in srgb, var(--accent-primary) 80%, black); }

  .kind-secondary { background: var(--surface-sunken); color: var(--text-primary); }
  .kind-secondary:hover:not(:disabled) { background: var(--surface-raised); }

  .kind-tertiary { background: transparent; color: var(--accent-primary); border-color: var(--accent-primary); }
  .kind-tertiary:hover:not(:disabled) { background: color-mix(in srgb, var(--accent-primary) 12%, transparent); }

  .kind-ghost { background: transparent; color: var(--text-secondary); }
  .kind-ghost:hover:not(:disabled) { background: var(--surface-sunken); color: var(--text-primary); }

  .kind-danger { background: var(--danger); color: var(--neutral-05); }
  .kind-danger:hover:not(:disabled) { background: color-mix(in srgb, var(--danger) 80%, black); }

  .label { line-height: 1; }
</style>