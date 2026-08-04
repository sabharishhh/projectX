<script>
  import { onMount } from "svelte";
  import { slide } from "svelte/transition";
  import { cubicOut } from "svelte/easing";

  import SidePanel from "./lib/components/SidePanel.svelte";
  import ConversationSidebar from "./lib/components/ConversationSidebar.svelte";
  import WorkspaceView from "./lib/components/workspace/WorkspaceView.svelte";

  import Button from './lib/components/ui/Button.svelte';
  import OpenPanelLeft from './lib/components/icons/IconPanelLeft.svelte';
  import OpenPanelRight from './lib/components/icons/IconPanelRight.svelte';

  import { globalMemory, loadMemory, loadHistory, loadConversations, clearMemory } from "./lib/stores/globalMemory.svelte.ts";
  import { getSession } from "./lib/stores/chatSessions.svelte.ts";
  import { workspace, initWorkspace, activeChatId, openTab, removeChatEverywhere, uiState, reconcileWorkspaceWithConversations } from "./lib/stores/workspace.svelte.ts";
  import { API_BASE } from "./lib/config.ts";

  function newConversationId() {
    return crypto.randomUUID();
  }

  function loadInitialConversationId() {
    const existing = localStorage.getItem("loki-conversation-id");
    if (existing) return existing;
    const fresh = newConversationId();
    localStorage.setItem("loki-conversation-id", fresh);
    return fresh;
  }

  let sidebarOpen = $state(true);

  onMount(async () => {
    initWorkspace(loadInitialConversationId());
    await Promise.all([loadMemory(), loadHistory(), loadConversations()]);
    await reconcileWorkspaceWithConversations();
    if (workspace.panes.every((p) => p.tabs.length === 0)) startNewChat();
  });

  function startNewChat() {
    openTab(newConversationId());
  }

  function switchConversation(id) {
    openTab(id);
  }

  async function deleteConversation(id) {
    await fetch(`${API_BASE}/api/messages/${id}`, { method: "DELETE" });
    removeChatEverywhere(id);
    if (workspace.panes.every((p) => p.tabs.length === 0)) startNewChat();
    await loadConversations();
  }

  async function createCommitment(content, deadline, branch = "main") {
    const isoDeadline = deadline ? `${deadline}T00:00:00Z` : null;
    const res = await fetch(`${API_BASE}/api/memory/commit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, branch, deadline: isoDeadline }),
    });
    const data = await res.json();
    if (data.ok) { await loadMemory(); await loadHistory(); }
  }

  async function deleteMemoryItem(unit) {
    const res = await fetch(`${API_BASE}/api/memory/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hash: unit.hash, branch: unit.branch }),
    });
    const data = await res.json();
    if (data.ok) { await loadMemory(); await loadHistory(); }
  }

  async function editMemoryItem(unit, newContent) {
    const res = await fetch(`${API_BASE}/api/memory/edit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        hash: unit.hash, branch: unit.branch, new_content: newContent,
        unit_type: unit.unit_type, provenance: unit.provenance,
        deadline: unit.deadline ?? null, commitment_status: unit.commitment_status ?? null,
      }),
    });
    const data = await res.json();
    if (data.ok) { await loadMemory(); await loadHistory(); }
  }

  let currentChatId = $derived(activeChatId());
  let sidePanelMessages = $derived(currentChatId ? getSession(currentChatId).messages : []);
</script>

<svelte:head>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link
    href="https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,400..700;1,400..700&family=Hanken+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
    rel="stylesheet"
  />
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css">
</svelte:head>

<div class="app">
  {#if sidebarOpen}
    <div class="sidebar-wrap" transition:slide={{ axis: 'x', duration: 300, easing: cubicOut }}>
      <div class="sidebar-inner">
        <ConversationSidebar
          conversations={globalMemory.conversations}
          activeId={currentChatId}
          onNew={startNewChat}
          onSelect={switchConversation}
          onDelete={deleteConversation}
          onToggle={() => (sidebarOpen = false)}
        />
      </div>
    </div>
  {/if}

  <section class="main">
  {#if !sidebarOpen}
    <div class="float-btn float-left">
      <Button kind="ghost" size="small" icon={OpenPanelLeft} iconDescription="Open sidebar" onclick={() => (sidebarOpen = true)} />
    </div>
  {/if}
  {#if !uiState.panelOpen}
    <div class="float-btn float-right">
      <Button kind="ghost" size="small" icon={OpenPanelRight} iconDescription="Open panel" onclick={() => (uiState.panelOpen = true)} />
    </div>
  {/if}

  <WorkspaceView />
</section>

  <SidePanel
    open={uiState.panelOpen}
    memory={globalMemory.memory}
    history={globalMemory.history}
    messages={sidePanelMessages}
    onClose={() => (uiState.panelOpen = false)}
    onopensource={(sourceId) => console.log("Source clicked:", sourceId)}
    ondelete={deleteMemoryItem}
    onedit={editMemoryItem}
    oncreate={createCommitment}
    onClearMemory={clearMemory}
  />
</div>

<style>
  .app {
    display: grid;
    grid-template-columns: auto 1fr;
    height: 100vh;
    font-family: var(--font-voice);
    color: var(--text-primary);
    background-color: var(--surface-page);
  }

  .sidebar-wrap {
    grid-column: 1;
    height: 100%;
    overflow: hidden;
  }

  .sidebar-inner {
    width: 220px;
    height: 100%;
  }

  .main {
    grid-column: 2;
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    position: relative;
  }

  .float-btn {
    position: absolute;
    top: 0.2rem;
    z-index: 5;
  }
  .float-left { left: 0.6rem; }
  .float-right { right: 0.6rem; }
</style>