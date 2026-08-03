<script>
  import { onMount } from "svelte";
  import { slide } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  
  import ActivityStrip from "./lib/components/ActivityStrip.svelte";
  import ConflictBlock from "./lib/components/ConflictBlock.svelte";
  import SidePanel from "./lib/components/SidePanel.svelte";
  import ConversationSidebar from "./lib/components/ConversationSidebar.svelte";
  import { renderMarkdown } from "./lib/markdown.js";
  import ForgetBlock from "./lib/components/ForgetBlock.svelte";

  import CodeMirror from "svelte-codemirror-editor";
  import { markdown } from "@codemirror/lang-markdown";
  import { keymap, EditorView } from "@codemirror/view";
  import { Prec } from "@codemirror/state";
  import { syntaxHighlighting, HighlightStyle } from "@codemirror/language";
  import { tags as t, Tag, styleTags } from "@lezer/highlight";


  import Button from './lib/components/ui/Button.svelte';
  import InlineNotification from './lib/components/ui/InlineNotification.svelte';
  import Loading from './lib/components/ui/Loading.svelte';
  import OpenPanelLeft from 'carbon-icons-svelte/lib/OpenPanelLeft.svelte';
  import OpenPanelRight from 'carbon-icons-svelte/lib/OpenPanelRight.svelte';

  const API_BASE = "http://127.0.0.1:8000";
  const MEMORY_BASE = "http://127.0.0.1:8100";

  const listMarkTag = Tag.define();
  const codeMarkTag = Tag.define();

  let latestText = "";

  const textSyncExtension = EditorView.updateListener.of((update) => {
    if (update.docChanged) {
      latestText = update.state.doc.toString();
    }
  });

  const customMarkdownExtension = {
    props: [
      styleTags({
        ListMark: listMarkTag,
        CodeMark: codeMarkTag               
      })
    ]
  };

  const nativeTextFeatures = EditorView.contentAttributes.of({
    spellcheck: "true",
    autocorrect: "on",
    autocapitalize: "on"
  });

  const submitKeymap = Prec.highest(
  keymap.of([
    {
      key: "Shift-Enter",
      run: () => false
    },
    {
      key: "Enter",
      run: (view) => {
        if (streaming) return false;
        sendMessage(view.state.doc.toString());
        return true;
      }
    }
  ])
);

  const customMarkdownStyle = HighlightStyle.define([
    {
      tag: t.monospace,
      backgroundColor: "var(--surface-sunken)",
      color: "var(--accent-memory)",
      borderRadius: "3px",
      padding: "2px 4px",
    },
    {
      tag: listMarkTag,
      color: "transparent", 
      display: "inline-block",
      width: "1ch", 
      backgroundImage: "radial-gradient(circle, var(--accent-memory) 35%, transparent 40%)", 
      backgroundPosition: "center",
      backgroundRepeat: "no-repeat",
      backgroundSize: "0.5em 0.5em"
    },
    {
      tag: codeMarkTag,
      color: "transparent",
      fontSize: "0px" 
    }
  ]);

  const editorExtensions = [
    markdown({
      extensions: [customMarkdownExtension]
    }), 
    syntaxHighlighting(customMarkdownStyle),
    EditorView.lineWrapping, 
    submitKeymap,  
    nativeTextFeatures,
    textSyncExtension
  ];

  

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

  function groupedActivity(activity) {
    const out = [];
    for (const act of visibleActivity(activity)) {
      if (act.kind === "tool_step") {
        const last = out[out.length - 1];
        if (last?.kind === "tool_group") {
          last.steps.push(act.label);
        } else {
          out.push({ kind: "tool_group", label: "Searching...", steps: [act.label] });
        }
      } else {
        out.push(act);
      }
    }
    return out;
  }

  let CONVERSATION_ID = $state(loadInitialConversationId());

  let messages = $state([]);
  let input = $state("");
  let streaming = $state(false);
  let processing = $state(false);
  let memory = $state([]);
  let conversations = $state([]);
  let history = $state([]);
  
  // UI States
  let sidebarOpen = $state(true);
  let panelOpen = $state(false);
  let scroller;

  onMount(async () => {
    await Promise.all([loadMessages(), loadMemory(), loadHistory(), loadConversations()]);
  });

  async function loadMessages() {
    const res = await fetch(`${API_BASE}/api/messages/${CONVERSATION_ID}`);
    const rawMessages = await res.json();
    
    messages = rawMessages.map(msg => {
      if (msg.activity) {
        msg.activity = msg.activity.filter(
          (a) => a.kind !== "searching" && a.kind !== "skill"
        );
      }
      return msg;
    });
  }

  async function loadMemory() {
    try {
      const branchesRes = await fetch(`${MEMORY_BASE}/branches`);
      const branchList = await branchesRes.json();
      const allBranches = branchList.length ? branchList : ["main"];

      const results = await Promise.all(
        allBranches.map((b) =>
          fetch(`${MEMORY_BASE}/state?branch=${encodeURIComponent(b)}`)
            .then((r) => r.json())
            .then((units) => units.map((u) => ({ ...u, branch: b })))
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

  async function loadHistory() {
    try {
      const branchesRes = await fetch(`${MEMORY_BASE}/branches`);
      const branchList = await branchesRes.json();
      const allBranches = branchList.length ? branchList : ["main"];

      const results = await Promise.all(
        allBranches.map((b) =>
          fetch(`${MEMORY_BASE}/history?branch=${encodeURIComponent(b)}`)
            .then((r) => r.json())
            .then((commits) => commits.map((c) => ({ ...c, branch: b })))
        )
      );

      history = results.flat().sort(
        (a, b) => new Date(b.created_at) - new Date(a.created_at)
      );
    } catch {
      history = [];
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
    localStorage.setItem("loki-conversation-id", CONVERSATION_ID);
    messages = [];
  }

  async function switchConversation(id) {
    if (id === CONVERSATION_ID) return;
    CONVERSATION_ID = id;
    localStorage.setItem("loki-conversation-id", CONVERSATION_ID);
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
    if (data.ok) { await loadMemory(); await loadHistory(); }
  }

  $effect(() => {
    messages.length;
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  });

  async function simulateReveal(msg, fullText) {
    const chunkSize = 3;
    const delayMs = 12;
    for (let idx = 0; idx < fullText.length; idx += chunkSize) {
      msg.content += fullText.slice(idx, idx + chunkSize);
      await new Promise((r) => setTimeout(r, delayMs));
    }
  }


  async function sendMessage(overrideText) {
    // Prioritize override (Enter key), then our sync tracker, then fallback to input
    const text = overrideText ?? latestText ?? input;
    if (!text.trim() || streaming) return;

    const userText = text;
    messages.push({ role: "user", content: userText });

    input = "";
    latestText = "";
    streaming = true;
    processing = true;

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
        processing = false;
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const ev = JSON.parse(line.slice(6));

          if (ev.type === "text") {
            messages[i].activity = messages[i].activity.filter(
              (a) => a.kind !== "searching" && a.kind !== "skill" && a.kind !== "correction_check"
            );
            if (ev.reveal === "simulated") {
              await simulateReveal(messages[i], ev.value);
            } else {
              messages[i].content += ev.value;
            }
          } else if (ev.type === "activity") {
            if (["search", "search_failed", "memory_read", "memory_write"].includes(ev.event.kind)) {
              messages[i].activity = messages[i].activity.filter(
                (a) => a.kind !== "searching" && a.kind !== "skill"
              );
            }
            messages[i].activity.push({ ...ev.event, open: false });
            if (ev.event.kind === "memory_write") { loadMemory(); loadHistory(); }
          } else if (ev.type === "error") {
            messages[i].error = ev.message;
          }
        }
      }
    } catch (e) {
      messages[i].error = e.message;
    }
    processing = false;
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
    await Promise.all([loadMessages(), loadMemory(), loadHistory()]);
  }

  async function deleteConversation(id) {
    await fetch(`${API_BASE}/api/messages/${id}`, { method: "DELETE" });
    if (id === CONVERSATION_ID) {
      await startNewChat();
    }
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

  async function resolveForget(act, choice) {
    const res = await fetch(`${API_BASE}/api/memory/forget`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ forget_id: act.id, choice }),
    });
    const data = await res.json();
    act.resolved = data.ok ? choice : "expired";
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

  function startResize(e) {
    resizingPanel = true;
    e.preventDefault();
    window.addEventListener("pointermove", onResize);
    window.addEventListener("pointerup", stopResize);
  }
  function onResize(e) {
    if (!resizingPanel) return;
    const newWidth = window.innerWidth - e.clientX;
    panelWidth = Math.min(640, Math.max(260, newWidth));
  }
  function stopResize() {
    resizingPanel = false;
    localStorage.setItem("loki-panel-width", String(panelWidth));
    window.removeEventListener("pointermove", onResize);
    window.removeEventListener("pointerup", stopResize);
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

  function citationSources(activity) {
    const sources = {};
    for (const act of activity ?? []) {
      if (act.kind === "source" && act.citation) {
        sources[act.citation] = { url: act.url, preview: act.preview };
      } else if (act.kind === "search" && act.results?.length) {
        act.results.forEach((r, i) => {
          sources[i + 1] = { url: r.url, title: r.title, preview: r.summary };
        });
      }
    }
    return sources;
  }

  function visibleActivity(activity) {
    return (activity ?? []).filter((a) => a.kind !== "source");
  }
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
          {conversations}
          activeId={CONVERSATION_ID}
          onNew={startNewChat}
          onSelect={switchConversation}
          onDelete={deleteConversation}
          onToggle={() => (sidebarOpen = false)} 
        />
      </div>
    </div>
  {/if}

  <section class="chat">
    <header>
      <div class="left-actions">
        {#if !sidebarOpen}
          <Button kind="ghost" size="small" icon={OpenPanelLeft} iconDescription="Open sidebar" onclick={() => (sidebarOpen = true)} />
        {/if}
      </div>
      <Button kind="ghost" size="small" onclick={clearChat}>Clear chat</Button>
      <Button kind="ghost" size="small" onclick={clearMemory}>Clear memory</Button>
      <div class="actions">
        {#if !panelOpen}
          <Button kind="ghost" size="small" icon={OpenPanelRight} iconDescription="Open panel" onclick={() => (panelOpen = true)} />
        {/if}
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

      {#each messages as msg, idx}
        {#if msg.role === "user"}
          <div class="turn user"><div class="said">{msg.content}</div></div>
        {:else}
          <div class="turn assistant">
            
            <!-- Processing indicator for the latest assistant message -->
            {#if processing && idx === messages.length - 1}
              <div class="processing-container">
                <div class="typing-indicator">
                  <span></span><span></span><span></span>
                </div>
              </div>
            {/if}

            <div class="prose">{@html renderMarkdown(msg.content, citationSources(msg.activity))}</div>

            {#if msg.error}
              <InlineNotification kind="error" title="Error" subtitle={msg.error} />
            {/if}

            {#each groupedActivity(msg.activity) as act}
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
      <div class="editor-wrapper">
        <CodeMirror
          bind:value={input}
          extensions={editorExtensions}
          placeholder="Ask loki"
        />
      </div>
      <Button size="field" kind="primary" disabled={streaming} onclick={() => sendMessage()}>
    {#if streaming}
      <Loading small withOverlay={false} description="Sending" />
    {:else}
      Send
    {/if}
  </Button>
    </div>
  </section>

  <SidePanel
    open={panelOpen}
    {memory} {history} {messages}
    onClose={() => (panelOpen = false)}
    onopensource={(sourceId) => console.log("Source clicked:", sourceId)}
    ondelete={deleteMemoryItem}
    onedit={editMemoryItem}
    oncreate={createCommitment}
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
    background-image:
      linear-gradient(color-mix(in srgb, var(--accent-primary) 5%, transparent) 1px, transparent 1px),
      linear-gradient(90deg, color-mix(in srgb, var(--accent-primary) 5%, transparent) 1px, transparent 1px);
    background-size: 26px 26px;
  }

  .editor-wrapper {
    flex: 1;
    max-width: 48rem;
  }

  /* Style the main CodeMirror container */
  .editor-wrapper :global(.cm-editor) {
    border: 0.5px solid var(--border-hairline);
    border-radius: var(--radius-sm);
    background: var(--surface-card);
    color: var(--text-primary);
    font-family: inherit;
    font-size: 0.95rem;
    line-height: 1.5;
  }

  /* Control the auto-expanding height & padding */
  .editor-wrapper :global(.cm-scroller) {
    min-height: 2.6rem;
    max-height: 40vh;
    overflow-y: auto;
    padding: 0.6rem 0.75rem;
    box-sizing: border-box;
  }

  /* Custom Focus Ring */
  .editor-wrapper :global(.cm-editor.cm-focused) {
    outline: 2px solid var(--accent-memory);
    outline-offset: -1px;
  }

  /* Grid Column Locks */
  .sidebar-wrap {
    grid-column: 1;
    height: 100%;
    overflow: hidden;
  }
  


  .chat {
    grid-column: 2; /* Forces the chat to always span the middle column */
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
  }

  .sidebar-inner {
    width: 220px;
    height: 100%;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.9rem 1.5rem;
    border-bottom: 0.5px solid var(--border-hairline);
  }

  .actions, .left-actions {
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }


  .processing-container {
    display: flex;
    align-items: center;
    padding: 0.5rem 0;
  }

  .typing-indicator {
    display: flex;
    gap: 4px;
    align-items: center;
  }

  .typing-indicator span {
    width: 6px;
    height: 6px;
    background-color: var(--text-muted); 
    border-radius: 50%;
    animation: bounce 1.4s infinite ease-in-out both;
  }

  .typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
  .typing-indicator span:nth-child(2) { animation-delay: -0.16s; }
  .typing-indicator span:nth-child(3) { animation-delay: 0s; }

  @keyframes bounce {
    0%, 80%, 100% {
      transform: scale(0);
      opacity: 0.5;
    }
    40% {
      transform: scale(1);
      opacity: 1;
    }
  }

  .stream {
    flex: 1;
    overflow-y: auto;
    padding: 2rem 1.5rem;
    display: flex;
    flex-direction: column;
    align-items: center; /* Centers the conversation flow */
    gap: 1.6rem;
  }

  /* Shared wrapper for centering the conversation */
  .turn {
    width: 100%;
    max-width: 48rem;
  }

  .turn.user {
    display: flex;
    justify-content: flex-end;
  }
  .said {
    max-width: 34rem;
    background: var(--accent-primary-bg);
    color: var(--text-primary);
    padding: 0.55rem 0.85rem;
    border-radius: var(--radius-md);
    font-size: 0.92rem;
    line-height: 1.5;
    white-space: pre-wrap;
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

  /* Explicitly restore bold styling to override CSS resets */
  .prose :global(strong),
  .prose :global(b) {
    font-weight: 600;
    color: var(--text-primary);
  }

  /* Restrict list styling to direct children only using '>' */
  .prose :global(ul) {
    list-style: none;
    margin: 0.5rem 0;
    padding-left: 1.3rem;
  }
  .prose :global(ul > li) {
    position: relative;
    margin: 0.35rem 0;
  }
  .prose :global(ul > li::before) {
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
  .prose :global(ol > li) {
    margin: 0.35rem 0;
  }
  .prose :global(ol > li::marker) {
    color: var(--accent-memory);
    font-weight: 600;
  }
  
  .prose :global(a) {
    color: var(--accent-primary);
  }

  .prose :global(.citation) {
    position: relative;
    display: inline-block;
  }
  .prose :global(.citation a) {
    font-size: 0.7em;
    vertical-align: super;
    color: var(--accent-primary);
    background: var(--surface-sunken);
    border-radius: 3px;
    padding: 0 0.3em;
    text-decoration: none;
    margin: 0 0.05em;
  }
  .prose :global(.citation a:hover) {
    color: var(--surface-page);
    background: var(--accent-primary);
  }
  .prose :global(.citation::after) {
    content: attr(data-preview);
    position: absolute;
    bottom: 100%;
    left: 50%;
    transform: translateX(-50%) translateY(-6px);
    width: max-content;
    max-width: 20rem;
    background: var(--surface-card);
    border: 0.5px solid var(--border-hairline);
    border-radius: var(--radius-sm);
    padding: 0.5rem 0.65rem;
    font-family: var(--font-technical);
    font-size: 0.72rem;
    line-height: 1.4;
    color: var(--text-secondary);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.12s ease;
    z-index: 20;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  }
  .prose :global(.citation:hover::after) {
    opacity: 1;
  }

  .prose :global(blockquote) {
    background: var(--surface-sunken);
    border-radius: var(--radius-sm);
    margin: 0.6rem 0;
    padding: var(--space-2) var(--space-3);
    color: var(--text-secondary);
    font-style: italic;
  }

  .prose :global(code) {
    font-family: var(--font-technical);
    font-size: 0.85em;
    background: var(--surface-sunken);
    padding: 0.1rem 0.35rem;
    border-radius: var(--radius-sm);
  }

  /* Table Styling */
  .prose :global(table) {
    width: 100%;
    border-collapse: collapse;
    margin: 1.2rem 0;
    font-size: 0.9rem;
    background: var(--surface-card);
    border-radius: var(--radius-sm);
    overflow: hidden; /* Keeps the rounded corners intact */
  }

  .prose :global(th),
  .prose :global(td) {
    padding: 0.6rem 0.85rem;
    border: 0.5px solid var(--border-hairline);
    text-align: left;
  }

  .prose :global(th) {
    background: var(--surface-sunken);
    font-weight: 600;
    color: var(--text-primary);
  }

  /* Optional: Subtle alternating row colors for readability */
  .prose :global(tr:nth-child(even)) {
    background: var(--surface-veil);
  }

  .prose :global(.code-block) {
    margin: 0.8rem 0;
    border-radius: 6px;
    overflow: hidden;
    background: var(--surface-sunken);
  }
  .prose :global(.code-block-header) {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.4rem 0.75rem;
    background: var(--surface-raised);
    border-bottom: 1px solid var(--border-hairline);
  }
  .prose :global(.code-lang) {
    font-family: var(--font-technical);
    font-size: 0.7rem;
    color: var(--text-muted);
    text-transform: lowercase;
  }
  .prose :global(.copy-btn) {
    font-family: var(--font-technical);
    font-size: 0.68rem;
    color: var(--text-secondary);
    background: none;
    border: none;
    border-radius: var(--radius-sm);
    padding: 0.15rem 0.5rem;
    cursor: pointer;
  }
  .prose :global(.copy-btn:hover) {
    background: var(--surface-sunken);
    color: var(--accent-primary-soft);
  }
  .prose :global(.code-block pre) {
    margin: 0;
    padding: 0.85rem 1rem;
    overflow-x: auto;
  }
  .prose :global(.code-block code) {
    font-family: var(--font-technical);
    font-size: 0.82rem;
    color: var(--text-primary);
    background: none !important;
    padding: 0;
  }

  .empty {
    color: var(--text-secondary);
    font-size: 0.9rem;
    font-style: italic;
  }

  .composer {
    display: flex;
    justify-content: center;
    gap: 0.5rem;
    align-items: flex-end;
    padding: 1rem 1.5rem 1.4rem;
    border-top: 0.5px solid var(--border-hairline);
  }

  .editor-wrapper :global(.cm-gutters) {
    display: none !important;
  }
  .editor-wrapper :global(.cm-activeLine) {
    background-color: transparent !important;
  }
  .editor-wrapper :global(.cm-content) {
    caret-color: var(--text-primary);
  }
</style>