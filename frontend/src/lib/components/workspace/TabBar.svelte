<script>
  let { paneId, tabs, activeTabId, onSelect, onClose, onReorder = () => {}, onCrossPaneDrop = () => {}, titleFor = (id) => id.slice(0, 8) } = $props();

  let draggedId = $state(null);
  let hoverId = $state(null);
  let hoverSide = $state(null);
  let barDragOver = $state(false);

  function handleDragStart(e, tabId) {
    draggedId = tabId;
    e.dataTransfer.setData('application/x-loki-tab', JSON.stringify({ chatId: tabId, sourcePaneId: paneId }));
    e.dataTransfer.effectAllowed = 'move';
  }

  function handleDragOver(e, tabId) {
    if (!e.dataTransfer.types.includes('application/x-loki-tab')) return;
    e.preventDefault();
    e.stopPropagation();
    const rect = e.currentTarget.getBoundingClientRect();
    hoverId = tabId;
    hoverSide = (e.clientX - rect.left) < rect.width / 2 ? 'before' : 'after';
  }

  function handleDragLeave() {
    hoverId = null;
    hoverSide = null;
  }

  function parsePayload(e) {
    try { return JSON.parse(e.dataTransfer.getData('application/x-loki-tab')); }
    catch { return null; }
  }

  function handleDrop(e, targetId) {
    if (!e.dataTransfer.types.includes('application/x-loki-tab')) return;
    e.preventDefault();
    e.stopPropagation();
    const payload = parsePayload(e);
    const side = hoverSide;
    hoverId = null;
    hoverSide = null;
    if (!payload || payload.chatId === targetId) return;
    onCrossPaneDrop(payload.sourcePaneId, payload.chatId, paneId, targetId, side);
  }

  function handleBarDragOver(e) {
    if (!e.dataTransfer.types.includes('application/x-loki-tab')) return;
    e.preventDefault();
    barDragOver = true;
  }

  function handleBarDrop(e) {
    if (!e.dataTransfer.types.includes('application/x-loki-tab')) return;
    e.preventDefault();
    barDragOver = false;
    const payload = parsePayload(e);
    if (!payload) return;
    onCrossPaneDrop(payload.sourcePaneId, payload.chatId, paneId, null, null);
  }

  function handleDragEnd() {
    draggedId = null;
    hoverId = null;
    hoverSide = null;
    barDragOver = false;
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="tab-bar"
  class:bar-drag-over={barDragOver && !hoverId}
  ondragover={handleBarDragOver}
  ondragleave={() => (barDragOver = false)}
  ondrop={handleBarDrop}
>
  {#each tabs as tabId (tabId)}
    <button
      class="tab"
      class:active={tabId === activeTabId}
      class:dragging={tabId === draggedId}
      class:drop-before={hoverId === tabId && hoverSide === 'before'}
      class:drop-after={hoverId === tabId && hoverSide === 'after'}
      draggable="true"
      ondragstart={(e) => handleDragStart(e, tabId)}
      ondragover={(e) => handleDragOver(e, tabId)}
      ondragleave={handleDragLeave}
      ondrop={(e) => handleDrop(e, tabId)}
      ondragend={handleDragEnd}
      onclick={() => onSelect(tabId)}
    >
      <span class="tab-label">{titleFor(tabId)}</span>
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <span class="tab-close" onclick={(e) => { e.stopPropagation(); onClose(tabId); }}>×</span>
    </button>
  {/each}
</div>

<style>
  .tab-bar { display: flex; overflow-x: auto; border-bottom: 0.5px solid var(--border-hairline); min-height: 2.1rem; }
  .tab-bar.bar-drag-over { background: color-mix(in srgb, var(--accent-primary) 6%, transparent); }
  .tab {
    display: flex; align-items: center; gap: 0.4rem;
    padding: 0.4rem 0.7rem; border: none; background: none;
    color: var(--text-secondary); cursor: pointer; white-space: nowrap;
    position: relative;
  }
  .tab.active { background: var(--surface-card); color: var(--text-primary); }
  .tab.dragging { opacity: 0.4; }
  .tab.drop-before::before,
  .tab.drop-after::after {
    content: '';
    position: absolute;
    top: 2px; bottom: 2px;
    width: 2px;
    background: var(--accent-primary);
  }
  .tab.drop-before::before { left: 0; }
  .tab.drop-after::after { right: 0; }
  .tab-close { opacity: 0.5; } .tab-close:hover { opacity: 1; }
</style>