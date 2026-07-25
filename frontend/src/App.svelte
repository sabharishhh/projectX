<script>
  import { onMount } from "svelte";
  import ActivityStrip from "./lib/ActivityStrip.svelte";
  import ConflictBlock from "./lib/ConflictBlock.svelte";
  import MemoryPanel from "./lib/MemoryPanel.svelte";
  import { renderMarkdown } from "./lib/markdown.js";

  const API_BASE = "http://127.0.0.1:8000";
  const MEMORY_BASE = "http://127.0.0.1:8100";

  function newConversationId() {
    return crypto.randomUUID();
  }

  let CONVERSATION_ID = localStorage.getItem("projectx-conversation-id") || newConversationId();
  localStorage.setItem("projectx-conversation-id", CONVERSATION_ID);


  let messages = $state([]);
  let input = $state("");
  let streaming = $state(false);
  let memory = $state([]);
  let panelOpen = $state(true);
  let scroller;

  onMount(async () => {
    await Promise.all([loadMessages(), loadMemory()]);
  });

  async function loadMessages() {
    const res = await fetch(`${API_BASE}/api/messages/${CONVERSATION_ID}`);
    messages = await res.json();
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

  async function loadBranches() {
    try {
      const res = await fetch(`${MEMORY_BASE}/branches`);
      const list = await res.json();
      branches = list.length ? list : ["main"];
    } catch {
      branches = ["main"];
    }
  }

  async function startNewChat() {
    CONVERSATION_ID = newConversationId();
    localStorage.setItem("projectx-conversation-id", CONVERSATION_ID);
    messages = [];
  }

  async function resolve(act, choice) {
    const res = await fetch(`${API_BASE}/api/memory/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conflict_id: act.id, choice }),
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
          } else if (ev.type === "activity") {
            if (ev.event.kind === "search" || ev.event.kind === "search_failed") {
              // remove the transient "searching…" note once the real result lands
              messages[i].activity = messages[i].activity.filter((a) => a.kind !== "searching");
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
    await loadBranches(); // a new branch may have just been created
  }

  async function clearChat() {
    await fetch(`${API_BASE}/api/messages/${CONVERSATION_ID}`, { method: "DELETE" });
    messages = [];
  }

  async function clearMemory() {
    await fetch(`${MEMORY_BASE}/reset`, { method: "POST" });
    await Promise.all([loadMessages(), loadMemory()]);
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

<div class="app" style:--cols={panelOpen ? "1fr 300px" : "1fr"}>
  <section class="chat">
    <header>
      <h1>projectX</h1>
      <div class="actions">
        <button onclick={startNewChat}>+ new chat</button>
        <button onclick={clearChat}>Clear chat</button>
        <button onclick={clearMemory}>Clear memory</button>
        <button class="toggle" onclick={() => (panelOpen = !panelOpen)}>
          {panelOpen ? "Hide memory" : "Show memory"}
        </button>
      </div>
    </header>

    <div class="stream" bind:this={scroller} onclick={handleStreamClick} onkeydown={handleStreamKeydown} role="presentation">
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
  :global(body) {
    margin: 0;
    background: #edeeec;
  }

  .app {
    --paper: #edeeec;
    --ink: #1a1d1a;
    --ink-soft: #5f665f;
    --rule: #d4d7d1;
    --verdigris: #2f6f62;
    --wash: #e2ebe7;

    display: grid;
    grid-template-columns: var(--cols, 1fr 300px);
    height: 100vh;
    font-family: "Instrument Sans", system-ui, sans-serif;
    color: var(--ink);
    background-color: var(--paper);
    background-image:
      linear-gradient(rgba(47, 111, 98, 0.05) 1px, transparent 1px),
      linear-gradient(90deg, rgba(47, 111, 98, 0.05) 1px, transparent 1px);
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
  }

  header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.9rem 1.5rem;
    border-bottom: 1px solid var(--rule);
  }
  h1 {
    margin: 0;
    font-size: 0.95rem;
    font-weight: 600;
    letter-spacing: -0.01em;
  }
  .actions {
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }
  .actions button {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.68rem;
    letter-spacing: 0.03em;
    color: var(--ink-soft);
    background: none;
    border: 1px solid var(--rule);
    border-radius: 2px;
    padding: 0.3rem 0.55rem;
    cursor: pointer;
  }
  .actions button:hover {
    color: var(--verdigris);
    border-color: var(--verdigris);
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
    background: var(--ink);
    color: var(--paper);
    padding: 0.55rem 0.85rem;
    border-radius: 3px;
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
    background: var(--verdigris);
  }

  .prose :global(ol) {
    margin: 0.5rem 0;
    padding-left: 1.4rem;
  }
  .prose :global(ol li) {
    margin: 0.35rem 0;
  }
  .prose :global(ol li::marker) {
    color: var(--verdigris);
    font-weight: 600;
  }

  .prose :global(a) {
    color: var(--verdigris);
  }
  .prose :global(blockquote) {
    border-left: 2px solid var(--rule);
    margin: 0.6rem 0;
    padding-left: 0.8rem;
    color: var(--ink-soft);
  }

  .prose :global(code) {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.85em;
    background: #e6e8e4;
    padding: 0.1rem 0.35rem;
    border-radius: 3px;
  }

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
    font-family: "JetBrains Mono", monospace;
    font-size: 0.7rem;
    color: #9aa39a;
    text-transform: lowercase;
  }
  .prose :global(.copy-btn) {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.68rem;
    color: #cfd3cc;
    background: none;
    border: 1px solid #4a4b47;
    border-radius: 3px;
    padding: 0.15rem 0.5rem;
    cursor: pointer;
  }
  .prose :global(.copy-btn:hover) {
    border-color: var(--verdigris);
    color: var(--verdigris);
  }
  .prose :global(.code-block pre) {
    margin: 0;
    padding: 0.85rem 1rem;
    overflow-x: auto;
  }
  .prose :global(.code-block code) {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.82rem;
    color: #e4e6e1;
    background: none;
    padding: 0;
  }

  .error {
    margin-top: 0.6rem;
    padding: 0.5rem 0.7rem;
    border-left: 2px solid #9c3b2e;
    background: #f2e4e1;
    font-size: 0.85rem;
  }
  .error .tag {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.62rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #9c3b2e;
    margin-right: 0.5rem;
  }

  .empty {
    color: var(--ink-soft);
    font-size: 0.9rem;
    font-style: italic;
  }

  .composer {
    display: flex;
    gap: 0.5rem;
    align-items: flex-end;
    padding: 1rem 1.5rem 1.4rem;
    border-top: 1px solid var(--rule);
  }
  textarea {
    flex: 1;
    resize: none;
    font: inherit;
    font-size: 0.95rem;
    line-height: 1.5;
    padding: 0.6rem 0.75rem;
    border: 1px solid var(--rule);
    border-radius: 3px;
    background: rgba(255, 255, 255, 0.55);
    color: var(--ink);
    min-height: 2.6rem;
    max-height: 40vh;
  }
  textarea:focus {
    outline: 2px solid var(--verdigris);
    outline-offset: -1px;
  }
  .send {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.72rem;
    letter-spacing: 0.05em;
    padding: 0.65rem 1.1rem;
    background: var(--verdigris);
    color: var(--paper);
    border: none;
    border-radius: 3px;
    cursor: pointer;
  }
  .send:disabled {
    opacity: 0.45;
    cursor: default;
  }

  @media (max-width: 820px) {
    .app {
      grid-template-columns: 1fr;
    }
    .panel-wrap {
      display: none;
    }
  }
</style>