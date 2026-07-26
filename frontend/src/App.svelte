<script>
  import { onMount } from "svelte";
  import ActivityStrip from "./lib/components/ActivityStrip.svelte";
  import ConflictBlock from "./lib/components/ConflictBlock.svelte";
  import MemoryPanel from "./lib/components/MemoryPanel.svelte";
  import ConversationSidebar from "./lib/components/ConversationSidebar.svelte";
  import { renderMarkdown } from "./lib/markdown.js";
  import ForgetBlock from "./lib/components/ForgetBlock.svelte";

  const API_BASE = "http://127.0.0.1:8000";
  const MEMORY_BASE = "http://127.0.0.1:8100";

  function newConversationId() {
    return crypto.randomUUID();
  }

  function loadInitialConversationId() {
    const existing = localStorage.getItem("projectx-conversation-id");
    if (existing) return existing;
    const fresh = newConversationId();
    localStorage.setItem("projectx-conversation-id", fresh);
    return fresh;
  }

  let CONVERSATION_ID = $state(loadInitialConversationId());

  let messages = $state([]);
  let input = $state("");
  let streaming = $state(false);
  let memory = $state([]);
  let conversations = $state([]);
  let panelOpen = $state(true);
  let scroller;

  onMount(async () => {
    await Promise.all([loadMessages(), loadMemory(), loadConversations()]);
  });

  async function loadMessages() {
    const res = await fetch(`${API_BASE}/api/messages/${CONVERSATION_ID}`);
    const rawMessages = await res.json();
    
    // Retroactively scrub orphaned loading states from historical database entries
    messages = rawMessages.map(msg => {
      if (msg.activity) {
        msg.activity = msg.activity.filter(
          (a) => a.kind !== "searching" && a.kind !== "skill"
        );
      }
      return msg;
    });
  }

  // aggregates across every branch — the user never needs to think about
  // branches existing at all; this is just "everything I know about you"
  async function loadMemory() {
    try {
      const branchesRes = await fetch(`${MEMORY_BASE}/branches`);
      const branchList = await branchesRes.json();
      const allBranches = branchList.length ? branchList : ["main"];

      const results = await Promise.all(
        allBranches.map((b) =>
          fetch(`${MEMORY_BASE}/state?branch=${encodeURIComponent(b)}`).then((r) => r.json())
        )
      );

      const seen = new Set();
      memory = results.flat().filter((u) => {
        if (seen.has(u.hash)) return false;
        seen.add(u.hash);
        return true;
      });
    } catch {
      memory = [];
    }
  }

  async function loadConversations() {
    try {
      const res = await fetch(`${API_BASE}/api/conversations`);
      conversations = await res.json();
    } catch {
      conversations = [];
    }
  }

  async function startNewChat() {
    CONVERSATION_ID = newConversationId();
    localStorage.setItem("projectx-conversation-id", CONVERSATION_ID);
    messages = [];
  }

  async function switchConversation(id) {
    if (id === CONVERSATION_ID) return;
    CONVERSATION_ID = id;
    localStorage.setItem("projectx-conversation-id", CONVERSATION_ID);
    await loadMessages();
  }

  async function resolve(act, choice) {
    const res = await fetch(`${API_BASE}/api/memory/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conflict_id: act.id, choice, conversation_id: CONVERSATION_ID }),
    });
    const data = await res.json();
    act.resolved = data.ok ? choice : "expired";
    if (data.ok) await loadMemory();
  }

  // keep the latest message in view as tokens arrive
  $effect(() => {
    messages.length;
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  });

  async function sendMessage() {
    if (!input.trim() || streaming) return;

    const userText = input;
    messages.push({ role: "user", content: userText });
    input = "";
    streaming = true;

    const i = messages.length;
    messages.push({ role: "assistant", content: "", activity: [], error: null });

    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: CONVERSATION_ID, message: userText }),
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const ev = JSON.parse(line.slice(6));

          if (ev.type === "text") {
            messages[i].content += ev.value;
            // 1. Scrub loading states completely when text starts streaming
            messages[i].activity = messages[i].activity.filter(
              (a) => a.kind !== "searching" && a.kind !== "skill"
            );
          } else if (ev.type === "activity") {
            // 2. Scrub loading states completely when ANY concrete result arrives
            if (["search", "search_failed", "memory_read", "memory_write"].includes(ev.event.kind)) {
              messages[i].activity = messages[i].activity.filter(
                (a) => a.kind !== "searching" && a.kind !== "skill"
              );
            }
            messages[i].activity.push({ ...ev.event, open: false });
            if (ev.event.kind === "memory_write") loadMemory();
          } else if (ev.type === "error") {
            messages[i].error = ev.message;
          }
        }
      }
    } catch (e) {
      messages[i].error = e.message;
    }
    streaming = false;
    await loadConversations(); 
  }

  async function clearChat() {
    await fetch(`${API_BASE}/api/messages/${CONVERSATION_ID}`, { method: "DELETE" });
    messages = [];
    await loadConversations();
  }

  async function clearMemory() {
    await fetch(`${MEMORY_BASE}/reset`, { method: "POST" });
    await Promise.all([loadMessages(), loadMemory()]);
  }

  async function deleteConversation(id) {
    await fetch(`${API_BASE}/api/messages/${id}`, { method: "DELETE" });
    if (id === CONVERSATION_ID) {
      // deleting the active thread — start a fresh one so there's
      // never a dangling reference to a conversation that no longer exists
      await startNewChat();
    }
    await loadConversations();
  }

  async function resolveForget(act, choice) {
    const res = await fetch(`${API_BASE}/api/memory/forget`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ forget_id: act.id, choice }),
    });
    const data = await res.json();
    act.resolved = data.ok ? choice : "expired";
    if (data.ok) await loadMemory();
  }

  function handleStreamClick(e) {
    const btn = e.target.closest(".copy-btn");
    if (!btn) return;
    const code = btn.closest(".code-block").querySelector("code");
    navigator.clipboard.writeText(code.textContent);
    const original = btn.textContent;
    btn.textContent = "Copied";
    setTimeout(() => (btn.textContent = original), 1200);
  }

  function handleStreamKeydown(e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    const btn = e.target.closest?.(".copy-btn");
    if (!btn) return;
    e.preventDefault();
    handleStreamClick(e);
  }

  function handleKeydown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }
</script>

<svelte:head>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link
    href="https://fonts.googleapis.com/css2?family=Instrument+Sans:ital,wght@0,400..700;1,400..700&family=JetBrains+Mono:wght@400;500&display=swap"
    rel="stylesheet"
  />
</svelte:head>

<div class="app" style:--cols={panelOpen ? "220px 1fr 300px" : "220px 1fr"}>
  <ConversationSidebar
    {conversations}
    activeId={CONVERSATION_ID}
    onNew={startNewChat}
    onSelect={switchConversation}
    onDelete={deleteConversation}
  />

  <section class="chat">
    <header>
      <div class="actions">
        <button onclick={clearChat}>Clear chat</button>
        <button onclick={clearMemory}>Clear memory</button>
        <button class="toggle" onclick={() => (panelOpen = !panelOpen)}>
          {panelOpen ? "Hide memory" : "Show memory"}
        </button>
      </div>
    </header>

    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="stream"
      bind:this={scroller}
      onclick={handleStreamClick}
      onkeydown={handleStreamKeydown}
    >
      {#if messages.length === 0}
        <p class="empty">Say something. What you reveal about yourself gets remembered.</p>
      {/if}

      {#each messages as msg}
        {#if msg.role === "user"}
          <div class="turn user"><div class="said">{msg.content}</div></div>
        {:else}
          <div class="turn assistant">
            <div class="prose">{@html renderMarkdown(msg.content)}</div>

            {#if msg.error}
              <div class="error"><span class="tag">error</span>{msg.error}</div>
            {/if}

            {#each msg.activity ?? [] as act}
              {#if act.kind === "conflict"}
                <ConflictBlock {act} onResolve={(choice) => resolve(act, choice)} />
              {:else if act.kind === "forget_request"}
                <ForgetBlock {act} onResolve={(choice) => resolveForget(act, choice)} />
              {:else}
                <ActivityStrip {act} />
              {/if}
            {/each}
          </div>
        {/if}
      {/each}
    </div>

    <div class="composer">
      <textarea
        bind:value={input}
        onkeydown={handleKeydown}
        placeholder="Type a message"
        rows="1"
        disabled={streaming}
      ></textarea>
      <button class="send" onclick={sendMessage} disabled={streaming}>
        {streaming ? "…" : "Send"}
      </button>
    </div>
  </section>

  {#if panelOpen}
    <div class="panel-wrap">
      <MemoryPanel {memory} />
    </div>
  {/if}
</div>

<style>
  .app {
    display: grid;
    grid-template-columns: var(--cols, 220px 1fr 300px);
    height: 100vh;
    font-family: var(--font-voice);
    color: var(--text-primary);
    background-color: var(--surface-page);
    background-image:
      linear-gradient(color-mix(in srgb, var(--accent-memory) 5%, transparent) 1px, transparent 1px),
      linear-gradient(90deg, color-mix(in srgb, var(--accent-memory) 5%, transparent) 1px, transparent 1px);
    background-size: 26px 26px;
  }

  .chat {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
  }

  .panel-wrap {
    min-height: 0;
    overflow-y: auto;
    padding: var(--space-4);
    border-left: 0.5px solid var(--border-hairline);
    background: var(--surface-veil);
  }

  header {
    display: flex;
    align-items: baseline;
    justify-content: flex-end;
    gap: 1rem;
    padding: 0.9rem 1.5rem;
    border-bottom: 0.5px solid var(--border-hairline);
  }
  .actions {
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }
  .actions button {
    font-family: var(--font-technical);
    font-size: 0.68rem;
    letter-spacing: 0.03em;
    color: var(--text-secondary);
    background: none;
    border: 0.5px solid var(--border-hairline);
    border-radius: var(--radius-sm);
    padding: 0.3rem 0.55rem;
    cursor: pointer;
  }
  .actions button:hover {
    color: var(--accent-memory);
    border-color: var(--accent-memory);
  }

  .stream {
    flex: 1;
    overflow-y: auto;
    padding: 2rem 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 1.6rem;
  }

  .turn.user {
    display: flex;
    justify-content: flex-end;
  }
  .said {
    max-width: 34rem;
    background: var(--text-primary);
    color: var(--surface-page);
    padding: 0.55rem 0.85rem;
    border-radius: var(--radius-sm);
    font-size: 0.92rem;
    line-height: 1.5;
    white-space: pre-wrap;
  }

  .turn.assistant {
    max-width: 42rem;
  }
  .prose {
    font-size: 0.98rem;
    line-height: 1.65;
  }
  .prose :global(p) {
    margin: 0.6rem 0;
  }
  .prose :global(p:first-child) {
    margin-top: 0;
  }

  .prose :global(h1),
  .prose :global(h2),
  .prose :global(h3) {
    margin: 1.1rem 0 0.5rem;
    font-weight: 600;
    line-height: 1.3;
  }
  .prose :global(h1) { font-size: 1.25rem; }
  .prose :global(h2) { font-size: 1.1rem; }
  .prose :global(h3) { font-size: 1rem; }

  .prose :global(ul) {
    list-style: none;
    margin: 0.5rem 0;
    padding-left: 1.3rem;
  }
  .prose :global(ul li) {
    position: relative;
    margin: 0.35rem 0;
  }
  .prose :global(ul li::before) {
    content: "";
    position: absolute;
    left: -1.05rem;
    top: 0.55em;
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--accent-memory);
  }

  .prose :global(ol) {
    margin: 0.5rem 0;
    padding-left: 1.4rem;
  }
  .prose :global(ol li) {
    margin: 0.35rem 0;
  }
  .prose :global(ol li::marker) {
    color: var(--accent-memory);
    font-weight: 600;
  }

  .prose :global(a) {
    color: var(--accent-memory);
  }
  .prose :global(blockquote) {
    border-left: 2px solid var(--border-hairline);
    margin: 0.6rem 0;
    padding-left: 0.8rem;
    color: var(--text-secondary);
  }

  .prose :global(code) {
    font-family: var(--font-technical);
    font-size: 0.85em;
    background: var(--surface-sunken);
    padding: 0.1rem 0.35rem;
    border-radius: var(--radius-sm);
  }

  /* code blocks stay a fixed dark "editor" look regardless of app theme —
     deliberate, not a token migration gap */
  .prose :global(.code-block) {
    margin: 0.8rem 0;
    border-radius: 6px;
    overflow: hidden;
    background: #292a28;
  }
  .prose :global(.code-block-header) {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.4rem 0.75rem;
    background: #201f1d;
    border-bottom: 1px solid #3a3b38;
  }
  .prose :global(.code-lang) {
    font-family: var(--font-technical);
    font-size: 0.7rem;
    color: #9aa39a;
    text-transform: lowercase;
  }
  .prose :global(.copy-btn) {
    font-family: var(--font-technical);
    font-size: 0.68rem;
    color: #cfd3cc;
    background: none;
    border: 1px solid #4a4b47;
    border-radius: 3px;
    padding: 0.15rem 0.5rem;
    cursor: pointer;
  }
  .prose :global(.copy-btn:hover) {
    border-color: var(--accent-memory);
    color: var(--accent-memory);
  }
  .prose :global(.code-block pre) {
    margin: 0;
    padding: 0.85rem 1rem;
    overflow-x: auto;
  }
  .prose :global(.code-block code) {
    font-family: var(--font-technical);
    font-size: 0.82rem;
    color: #e4e6e1;
    background: none;
    padding: 0;
  }

  .error {
    margin-top: 0.6rem;
    padding: 0.5rem 0.7rem;
    border-left: 2px solid var(--border-danger);
    background: var(--bg-danger);
    font-size: 0.85rem;
  }
  .error .tag {
    font-family: var(--font-technical);
    font-size: 0.62rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-danger);
    margin-right: 0.5rem;
  }

  .empty {
    color: var(--text-secondary);
    font-size: 0.9rem;
    font-style: italic;
  }

  .composer {
    display: flex;
    gap: 0.5rem;
    align-items: flex-end;
    padding: 1rem 1.5rem 1.4rem;
    border-top: 0.5px solid var(--border-hairline);
  }
  textarea {
    flex: 1;
    resize: none;
    font: inherit;
    font-size: 0.95rem;
    line-height: 1.5;
    padding: 0.6rem 0.75rem;
    border: 0.5px solid var(--border-hairline);
    border-radius: var(--radius-sm);
    background: var(--surface-card);
    color: var(--text-primary);
    min-height: 2.6rem;
    max-height: 40vh;
  }
  textarea:focus {
    outline: 2px solid var(--accent-memory);
    outline-offset: -1px;
  }
  .send {
    font-family: var(--font-technical);
    font-size: 0.72rem;
    letter-spacing: 0.05em;
    padding: 0.65rem 1.1rem;
    background: var(--accent-memory);
    color: var(--surface-page);
    border: none;
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .send:disabled {
    opacity: 0.45;
    cursor: default;
  }
</style>