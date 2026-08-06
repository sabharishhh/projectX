<script>
  import { fade, fly } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  import Close from './icons/IconClose.svelte';
  import TrashCan from './icons/IconTrash.svelte';
  import Button from './ui/Button.svelte';
  import Tabs from './ui/Tabs.svelte';
  import TabPanel from './ui/TabPanel.svelte';
  import MemoryView from './MemoryView.svelte';
  import TimelineView from './TimelineView.svelte';
  import SourcesView from './SourcesView.svelte';

  let {
    open = false, memory = [], history = [], messages = [],
    onClose = () => {}, onopensource = () => {}, ondelete = () => {}, onedit = () => {}, oncreate = () => {},
    onClearMemory = () => {},
  } = $props();

  let selectedTab = $state(0);
  const TAB_TITLES = ['Memory', 'Timeline', 'Sources'];

  function handleKeydown(e) {
    if (e.key === 'Escape' && open) onClose();
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
  <div class="backdrop" transition:fade={{ duration: 200 }} onclick={onClose} role="presentation"></div>
  <aside class="drawer" transition:fly={{ x: 40, duration: 280, easing: cubicOut }} aria-label="Memory, timeline and sources panel">
    <header class="drawer-header">
      <h2>{TAB_TITLES[selectedTab]}</h2>
      <div class="header-actions">
        <Button kind="ghost" size="small" icon={TrashCan} iconDescription="Clear memory" onclick={onClearMemory} />
        <Button kind="ghost" size="small" icon={Close} iconDescription="Close" onclick={onClose} />
      </div>
    </header>

    <div class="tabs-wrap">
      <Tabs labels={TAB_TITLES} bind:selected={selectedTab} accent="var(--accent-attention)">
        <TabPanel index={0} selected={selectedTab}><MemoryView {memory} {onopensource} {ondelete} {onedit} {oncreate} /></TabPanel>
        <TabPanel index={1} selected={selectedTab}><TimelineView {history} /></TabPanel>
        <TabPanel index={2} selected={selectedTab}><SourcesView {messages} /></TabPanel>
      </Tabs>
    </div>
  </aside>
{/if}

<style>
  .backdrop { position: fixed; inset: 0; background: var(--surface-overlay-backdrop); z-index: 40; }
  .drawer {
    position: fixed; top: 0; right: 0; bottom: 0;
    width: min(var(--panel-width), 92vw); max-width: 480px;
    background: var(--surface-card); border-left: 1px solid var(--border-hairline);
    box-shadow: -8px 0 24px rgba(0,0,0,0.35);
    z-index: 41; display: flex; flex-direction: column; overflow: hidden;
  }
  .drawer-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 0.9rem 1.5rem; border-bottom: 0.5px solid var(--border-hairline); flex-shrink: 0;
  }
  .drawer-header h2 { margin: 0; font-family: var(--font-display); font-size: var(--size-title); font-weight: var(--weight-semibold); color: var(--text-primary); }
  .header-actions { display: flex; align-items: center; gap: 0.3rem; }

  .tabs-wrap { flex: 1; min-height: 0; display: flex; flex-direction: column; }
</style>