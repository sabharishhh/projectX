<script>
  let { labels = [], selected = $bindable(0), children } = $props();
  let tabRefs = [];

  function select(i) { selected = i; tabRefs[i]?.focus(); }

  function onKeydown(e, i) {
    if (e.key === 'ArrowRight') { e.preventDefault(); select((i + 1) % labels.length); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); select((i - 1 + labels.length) % labels.length); }
    else if (e.key === 'Home') { e.preventDefault(); select(0); }
    else if (e.key === 'End') { e.preventDefault(); select(labels.length - 1); }
  }
</script>

<div class="tabs">
  <div class="tablist" role="tablist">
    {#each labels as label, i}
      <button
        bind:this={tabRefs[i]}
        role="tab"
        id="tab-{i}"
        aria-controls="panel-{i}"
        aria-selected={selected === i}
        tabindex={selected === i ? 0 : -1}
        class="tab"
        class:selected={selected === i}
        onclick={() => select(i)}
        onkeydown={(e) => onKeydown(e, i)}
      >
        {label}
      </button>
    {/each}
  </div>
  <div class="panels">{@render children?.()}</div>
</div>

<style>
  .tabs { display: flex; flex-direction: column; height: 100%; }
  .tablist { display: flex; border-bottom: 1px solid var(--border-hairline); flex-shrink: 0; }
  .tab {
    flex: 1; padding: var(--space-3) var(--space-2);
    background: none; border: none; border-bottom: 2px solid transparent;
    font-family: var(--font-voice); font-size: var(--size-meta); font-weight: var(--weight-medium);
    color: var(--text-secondary); cursor: pointer;
    transition: color var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
  }
  .tab:hover { color: var(--text-primary); }
  .tab.selected { color: var(--text-primary); border-bottom-color: var(--accent-primary); }
  .tab:focus-visible { outline: 2px solid var(--accent-primary); outline-offset: -2px; }
  .panels { flex: 1; overflow-y: auto; padding: var(--space-4); }
</style>