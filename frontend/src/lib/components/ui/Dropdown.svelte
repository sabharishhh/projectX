<script>
  import { tick } from 'svelte';

  let { items = [], selectedId = $bindable(null), titleText = '' } = $props();

  let open = $state(false);
  let activeIndex = $state(-1);
  let triggerEl = $state();
  let listboxEl = $state();
  let typeahead = '';
  let typeaheadTimer;

  const selectedItem = $derived(items.find((i) => i.id === selectedId) ?? null);

  async function openList() {
    open = true;
    activeIndex = Math.max(0, items.findIndex((i) => i.id === selectedId));
    await tick();
    listboxEl?.focus();
  }
  function closeList(focusTrigger = true) {
    open = false;
    activeIndex = -1;
    if (focusTrigger) triggerEl?.focus();
  }
  function choose(i) {
    selectedId = items[i]?.id ?? selectedId;
    closeList();
  }
  function onTriggerKeydown(e) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      openList();
    }
  }
  function onListKeydown(e) {
    if (e.key === 'Escape') { e.preventDefault(); closeList(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); activeIndex = (activeIndex + 1) % items.length; }
    else if (e.key === 'ArrowUp') { e.preventDefault(); activeIndex = (activeIndex - 1 + items.length) % items.length; }
    else if (e.key === 'Home') { e.preventDefault(); activeIndex = 0; }
    else if (e.key === 'End') { e.preventDefault(); activeIndex = items.length - 1; }
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(activeIndex); }
    else if (e.key === 'Tab') { closeList(false); }
    else if (e.key.length === 1) { typeaheadJump(e.key); }
  }
  function typeaheadJump(char) {
    clearTimeout(typeaheadTimer);
    typeahead += char.toLowerCase();
    const start = (activeIndex + 1) % items.length;
    const match = [...items.slice(start), ...items.slice(0, start)].findIndex((i) => i.text.toLowerCase().startsWith(typeahead));
    if (match !== -1) activeIndex = (start + match) % items.length;
    typeaheadTimer = setTimeout(() => (typeahead = ''), 500);
  }
  function handleOutsideClick(e) {
    if (open && !triggerEl?.contains(e.target) && !listboxEl?.contains(e.target)) closeList(false);
  }
</script>

<svelte:window onclick={handleOutsideClick} />

<div class="dropdown">
  {#if titleText}<span class="label" id="dd-label">{titleText}</span>{/if}
  <button
    bind:this={triggerEl}
    type="button"
    class="trigger"
    role="combobox"
    aria-haspopup="listbox"
    aria-expanded={open}
    aria-controls="dd-listbox"
    aria-labelledby={titleText ? 'dd-label' : undefined}
    aria-activedescendant={open && activeIndex >= 0 ? `dd-opt-${activeIndex}` : undefined}
    onclick={() => (open ? closeList() : openList())}
    onkeydown={onTriggerKeydown}
  >
    <span class="value">{selectedItem?.text ?? 'Select…'}</span>
    <svg class="chevron" class:open viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
      <path d="M3 4.5 6 7.5 9 4.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  </button>

  {#if open}
    <ul bind:this={listboxEl} id="dd-listbox" class="listbox" role="listbox" aria-labelledby={titleText ? 'dd-label' : undefined} tabindex="-1" onkeydown={onListKeydown}>
      {#each items as item, i (item.id)}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
        <li
          id="dd-opt-{i}"
          role="option"
          aria-selected={item.id === selectedId}
          class="option"
          class:active={i === activeIndex}
          class:selected={item.id === selectedId}
          onclick={() => choose(i)}
          onmouseenter={() => (activeIndex = i)}
        >
          {item.text}
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .dropdown { position: relative; display: flex; flex-direction: column; gap: var(--space-1); }
  .label { font-size: var(--size-caption); color: var(--text-secondary); font-weight: var(--weight-medium); }
  .trigger {
    display: flex; align-items: center; justify-content: space-between; gap: var(--space-2);
    width: 100%; height: 2.5rem; padding: 0 var(--space-3);
    background: var(--surface-sunken); border: 1px solid var(--border-hairline); border-radius: var(--radius-sm);
    color: var(--text-primary); font-family: var(--font-voice); font-size: var(--size-meta);
    cursor: pointer; text-align: left;
  }
  .trigger:hover { background: var(--surface-raised); }
  .trigger:focus-visible, .trigger[aria-expanded="true"] { outline: 2px solid var(--accent-primary); outline-offset: -1px; }
  .chevron { flex-shrink: 0; color: var(--text-muted); transition: transform var(--dur-fast) var(--ease-out); }
  .chevron.open { transform: rotate(180deg); }

  .listbox {
    position: absolute; top: calc(100% + 4px); left: 0; right: 0; z-index: 50;
    max-height: 14rem; overflow-y: auto;
    background: var(--surface-raised); border: 1px solid var(--border-strong); border-radius: var(--radius-sm);
    list-style: none; margin: 0; padding: var(--space-1);
    box-shadow: 0 4px 16px rgba(0,0,0,0.4);
  }
  .listbox:focus { outline: none; }
  .option { padding: var(--space-2) var(--space-3); border-radius: var(--radius-sm); font-size: var(--size-meta); color: var(--text-primary); cursor: pointer; }
  .option.active { background: var(--surface-sunken); }
  .option.selected { color: var(--accent-primary); font-weight: var(--weight-medium); }
</style>