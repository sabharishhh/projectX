<script>
  import TabBar from "./TabBar.svelte";
  import ChatWindow from "./ChatWindow.svelte";
  import { workspace, selectTab as selectTabInWorkspace, closeTab as closeTabInWorkspace, openTab, moveTabToPane } from "../../stores/workspace.svelte.ts";
  import { globalMemory } from "../../stores/globalMemory.svelte.ts";

  let { pane } = $props();
  let isDragOver = $state(false);

  function handleCrossPaneDrop(sourcePaneId, chatId, targetPaneId, targetChatId, side) {
    moveTabToPane(sourcePaneId, chatId, targetPaneId, targetChatId, side);
  }

  function selectTab(id) {
    selectTabInWorkspace(pane.id, id);
  }

  function closeTab(id) {
    closeTabInWorkspace(pane.id, id);
  }

  function titleFor(chatId) {
    return globalMemory.conversations.find((c) => c.conversation_id === chatId)?.label ?? "Untitled";
  }

  function handleDrop(e) {
    e.preventDefault();
    isDragOver = false;
    const chatId = e.dataTransfer.getData('text/plain');
    if (chatId) openTab(chatId, pane.id);
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<!-- svelte-ignore a11y_click_events_have_key_events -->
<div
  class="pane"
  class:drag-over={isDragOver}
  onclick={() => (workspace.activePaneId = pane.id)}
  ondragover={(e) => { e.preventDefault(); isDragOver = true; }}
  ondragleave={() => (isDragOver = false)}
  ondrop={handleDrop}
>
  <TabBar paneId={pane.id} tabs={pane.tabs} activeTabId={pane.activeTabId} onSelect={selectTab} onClose={closeTab} onCrossPaneDrop={handleCrossPaneDrop} {titleFor} />
  <div class="pane-body">
    {#each pane.tabs as tabId (tabId)}
      <div class="tab-content" style:display={tabId === pane.activeTabId ? "flex" : "none"}>
        <ChatWindow chatId={tabId} />
      </div>
    {/each}
  </div>
</div>

<style>
  .pane { display: flex; flex-direction: column; min-width: 0; min-height: 0; height: 100%; background: var(--surface-page); position: relative; }
  .pane.drag-over::after {
    content: '';
    position: absolute;
    inset: 0;
    border: 2px dashed var(--accent-primary);
    background: color-mix(in srgb, var(--accent-primary) 8%, transparent);
    pointer-events: none;
    z-index: 3;
  }
  .pane-body { flex: 1; min-height: 0; position: relative; }
  .tab-content { flex-direction: column; height: 100%; }
</style>