<script>
  import { onMount } from "svelte";

  const API_BASE = "http://127.0.0.1:8000";
  const MEMORY_BASE = "http://127.0.0.1:8100";
  const CONVERSATION_ID = "default";

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

  async function loadMemory() {
    try {
      const res = await fetch(`${MEMORY_BASE}/state`);
      memory = await res.json();
    } catch {
      memory = [];
    }
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
  }

  async function clearChat() {
    await fetch(`${API_BASE}/api/messages/${CONVERSATION_ID}`, { method: "DELETE" });
    messages = [];
  }

  async function clearMemory() {
    await fetch(`${MEMORY_BASE}/reset`, { method: "POST" });
    await loadMemory();
  }

  function handleKeydown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  // minimal markdown: fenced code, inline code, bold
  function render(text) {
    const esc = (s) =>
      s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

    const parts = text.split(/```(\w*)\n?([\s\S]*?)```/g);
    let out = "";
    for (let i = 0; i < parts.length; i++) {
      if (i % 3 === 0) {
        out += esc(parts[i])
          .replace(/`([^`]+)`/g, "<code>$1</code>")
          .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
          .replace(/\n/g, "<br>");
      } else if (i % 3 === 2) {
        out += `<pre><code>${esc(parts[i])}</code></pre>`;
      }
    }
    return out;
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

<div class="app">
  <section class="chat">
    <header>
      <h1>projectX</h1>
      <div class="actions">
        <button onclick={clearChat}>Clear chat</button>
        <button onclick={clearMemory}>Clear memory</button>
        <button class="toggle" onclick={() => (panelOpen = !panelOpen)}>
          {panelOpen ? "Hide memory" : "Show memory"}
        </button>
      </div>
    </header>

    <div class="stream" bind:this={scroller}>
      {#if messages.length === 0}
        <p class="empty">Say something. What you reveal about yourself gets remembered.</p>
      {/if}

      {#each messages as msg}
        {#if msg.role === "user"}
          <div class="turn user"><div class="said">{msg.content}</div></div>
        {:else}
          <div class="turn assistant">
            <div class="prose">{@html render(msg.content)}</div>

            {#if msg.error}
              <div class="error"><span class="tag">error</span>{msg.error}</div>
            {/if}

            {#each msg.activity ?? [] as act}
              {#if act.kind === "conflict"}
                <div class="activity conflict">
                  <div class="act-head static">{act.label}</div>
                  <div class="conflict-body">
                    <p class="was"><span class="meta">stored</span>{act.old.content}</p>
                    <p class="now"><span class="meta">just now</span>{act.new.content}</p>

                    {#if act.resolved}
                      <p class="resolved">
                        {act.resolved === "update"
                          ? "Updated."
                          : act.resolved === "keep_both"
                            ? "Keeping both."
                            : act.resolved === "expired"
                              ? "This decision expired (server restarted since) — check current memory."
                              : "Kept the original."}
                      </p>
                    {:else}
                      <div class="choices">
                        <button onclick={() => resolve(act, "update")}>Replace it</button>
                        <button onclick={() => resolve(act, "keep_both")}>Both are true</button>
                        <button onclick={() => resolve(act, "keep_old")}>Ignore this</button>
                      </div>
                    {/if}
                  </div>
                </div>
              {:else}
                <div class="activity {act.kind}">
                  <button class="act-head" onclick={() => (act.open = !act.open)}>
                    <span class="chev">{act.open ? "−" : "+"}</span>
                    {act.label}
                  </button>
                  {#if act.open}
                    <ul class="act-body">
                      {#each act.units as u}
                        <li>
                          <span class="meta">{u.unit_type} · {u.provenance}</span>
                          {u.content}
                        </li>
                      {/each}
                    </ul>
                  {/if}
                </div>
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
    <aside class="panel">
      <div class="panel-head">
        <span class="meta">memory</span>
        <span class="count">{memory.length}</span>
      </div>

      {#if memory.length === 0}
        <p class="empty small">Nothing stored yet.</p>
      {:else}
        {#each memory as u}
          <article class="card">
            <span class="meta">{u.unit_type} · {u.provenance}</span>
            <p>{u.content}</p>
            <span class="hash">{u.hash.slice(0, 12)}</span>
          </article>
        {/each}
      {/if}
    </aside>
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
    grid-template-columns: 1fr 300px;
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
  .prose :global(pre) {
    background: #e6e8e4;
    border-left: 2px solid var(--verdigris);
    padding: 0.7rem 0.9rem;
    overflow-x: auto;
    margin: 0.7rem 0;
  }
  .prose :global(code) {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.82rem;
  }

  .activity {
    margin-top: 0.7rem;
    border: 1px dashed var(--verdigris);
    border-radius: 2px;
    background: var(--wash);
  }
  .act-head {
    width: 100%;
    text-align: left;
    background: none;
    border: none;
    cursor: pointer;
    padding: 0.4rem 0.6rem;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.7rem;
    letter-spacing: 0.03em;
    color: var(--verdigris);
  }
  .chev {
    display: inline-block;
    width: 0.9rem;
  }
  .act-body {
    margin: 0;
    padding: 0 0.6rem 0.5rem 1.5rem;
    list-style: none;
  }
  .act-body li {
    font-size: 0.85rem;
    line-height: 1.5;
    padding: 0.25rem 0;
  }

  .meta {
    display: block;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.62rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--verdigris);
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
  .empty.small {
    font-size: 0.8rem;
    padding: 0 1rem;
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

  .panel {
    border-left: 1px solid var(--rule);
    overflow-y: auto;
    padding: 0.9rem 1rem 2rem;
    background: rgba(255, 255, 255, 0.35);
  }
  .panel-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding-bottom: 0.6rem;
    border-bottom: 1px solid var(--rule);
    margin-bottom: 0.9rem;
  }
  .count {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.7rem;
    color: var(--ink-soft);
  }
  .card {
    border-left: 2px solid var(--verdigris);
    padding: 0.35rem 0 0.35rem 0.6rem;
    margin-bottom: 1rem;
  }
  .card p {
    margin: 0.25rem 0 0.3rem;
    font-size: 0.85rem;
    line-height: 1.45;
  }
  .hash {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.6rem;
    color: #9aa39a;
  }
  .activity.conflict {
    border-style: solid;
    border-color: #b07d2b;
    background: #f6efe0;
  }
  .act-head.static {
    padding: 0.4rem 0.6rem;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.7rem;
    letter-spacing: 0.03em;
    color: #8a5f1c;
  }
  .conflict-body {
    padding: 0 0.7rem 0.6rem;
  }
  .conflict-body p {
    margin: 0.3rem 0;
    font-size: 0.86rem;
    line-height: 1.45;
  }
  .conflict-body .meta {
    color: #8a5f1c;
  }
  .was {
    opacity: 0.65;
  }
  .choices {
    display: flex;
    gap: 0.4rem;
    margin-top: 0.6rem;
  }
  .choices button {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.68rem;
    padding: 0.3rem 0.6rem;
    border: 1px solid #b07d2b;
    border-radius: 2px;
    background: none;
    color: #8a5f1c;
    cursor: pointer;
  }
  .choices button:hover {
    background: #b07d2b;
    color: #f6efe0;
  }
  .resolved {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.68rem;
    color: #8a5f1c;
    margin-top: 0.5rem;
  }

  @media (max-width: 820px) {
    .app {
      grid-template-columns: 1fr;
    }
    .panel {
      display: none;
    }
  }
</style>