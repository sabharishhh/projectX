<script>
  import CodeMirror from "svelte-codemirror-editor";
  import { markdown } from "@codemirror/lang-markdown";
  import { keymap, EditorView } from "@codemirror/view";
  import { Prec } from "@codemirror/state";
  import { syntaxHighlighting, HighlightStyle } from "@codemirror/language";
  import { tags as t, Tag, styleTags } from "@lezer/highlight";
  import CommitmentResolutionBlock from "../CommitmentResolutionBlock.svelte";

  import { getSession, sendMessage, clearChat } from "../../stores/chatSessions.svelte.ts";
  import { loadMemory, loadHistory, loadConversations, editMemoryItem } from "../../stores/globalMemory.svelte.ts";
  import { splitPane, activeChatId, composeEditState, cancelMemoryEdit } from "../../stores/workspace.svelte.ts";
  import { renderMarkdown } from "../../markdown.js";

  import ActivityStrip from "../ActivityStrip.svelte";
  import ConflictBlock from "../ConflictBlock.svelte";
  import ForgetBlock from "../ForgetBlock.svelte";
  import InlineNotification from "../ui/InlineNotification.svelte";
  import Button from "../ui/Button.svelte";
  import TrashCan from '../icons/IconTrash.svelte';
  import OverflowMenuVertical from '../icons/IconMoreVertical.svelte';
  import ColumnDependency from '../icons/IconSplit.svelte';
  import IconPlus from '../icons/IconPlus.svelte';
  import IconMic from '../icons/IconMic.svelte';
  import IconSend from '../icons/IconSend.svelte';
  import IconSpinner from '../icons/IconSpinner.svelte';
  import IconCheck from '../icons/IconCheck.svelte';
  import IconClose from '../icons/IconClose.svelte';

  import { API_BASE } from "../../config.ts";

  let { chatId } = $props();
  let session = $derived(getSession(chatId));
  let latestText = $state("");
  let scroller;
  let menuOpen = $state(false);
  let menuWrap;
  let composerEl;
  let isMultiline = $state(false);

  let isEditingMemory = $derived(composeEditState.unit !== null && chatId === activeChatId());

  $effect(() => {
    if (isEditingMemory) {
      const content = composeEditState.unit.content;
      session.input = content;
      latestText = content;
    }
  });

  $effect(() => {
    if (!composerEl) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        isMultiline = entry.contentRect.height > 48;
      }
    });
    ro.observe(composerEl);
    return () => ro.disconnect();
  });

  $effect(() => {
    session.messages.length;
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  });

  const listMarkTag = Tag.define();
  const codeMarkTag = Tag.define();

  const textSyncExtension = EditorView.updateListener.of((update) => {
    if (update.docChanged) {
      latestText = update.state.doc.toString();
    }
  });

  const customMarkdownExtension = { props: [styleTags({ ListMark: listMarkTag, CodeMark: codeMarkTag })] };
  const nativeTextFeatures = EditorView.contentAttributes.of({
    spellcheck: "true", autocorrect: "on", autocapitalize: "on",
  });
  const submitKeymap = Prec.highest(
    keymap.of([
      { key: "Shift-Enter", run: () => false },
      {
        key: "Enter",
        run: (view) => {
          if (session.streaming) return false;
          handleSend(view.state.doc.toString());
          return true;
        },
      },
    ])
  );
  const customMarkdownStyle = HighlightStyle.define([
    { tag: t.monospace, backgroundColor: "var(--surface-sunken)", color: "var(--accent-memory)", borderRadius: "3px", padding: "2px 4px" },
    {
      tag: listMarkTag, color: "transparent", display: "inline-block", width: "1ch",
      backgroundImage: "radial-gradient(circle, var(--accent-memory) 35%, transparent 40%)",
      backgroundPosition: "center", backgroundRepeat: "no-repeat", backgroundSize: "0.5em 0.5em",
    },
    { tag: codeMarkTag, color: "transparent", fontSize: "0px" },
  ]);
  const editorExtensions = [
    markdown({ extensions: [customMarkdownExtension] }),
    syntaxHighlighting(customMarkdownStyle),
    EditorView.lineWrapping,
    submitKeymap,
    nativeTextFeatures,
    textSyncExtension,
  ];

  async function resolveCommitmentRequest(act, choice) {
    const res = await fetch(`${API_BASE}/api/memory/resolve_commitment`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resolution_id: act.id, choice }),
    });
    const data = await res.json();
    act.resolved = data.ok ? choice : "expired";
    if (data.ok) { await loadMemory(); await loadHistory(); }
  }

  async function handleSend(overrideText) {
    const text = overrideText ?? latestText ?? session.input;
    if (!text.trim() || session.streaming) return;

    if (isEditingMemory) {
      const unit = composeEditState.unit;
      session.input = "";
      latestText = "";
      cancelMemoryEdit();
      await editMemoryItem(unit, text.trim());
      return;
    }

    latestText = "";
    await sendMessage(chatId, API_BASE, text, {
      onMemoryWrite: () => { loadMemory(); loadHistory(); },
    });
    await loadConversations();
  }

  function handleCancelEdit() {
    session.input = "";
    latestText = "";
    cancelMemoryEdit();
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

  function handleClearChat() {
    menuOpen = false;
    clearChat(chatId, API_BASE);
  }

  function handleSplitPane() {
    menuOpen = false;
    splitPane();
  }

  function handleWindowClick(e) {
    if (menuOpen && menuWrap && !menuWrap.contains(e.target)) menuOpen = false;
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

  function groupedActivity(activity) {
    const out = [];
    for (const act of (activity ?? []).filter((a) => a.kind !== "source")) {
      if (act.kind === "tool_step") {
        const last = out[out.length - 1];
        if (last?.kind === "tool_group") last.steps.push(act.label);
        else out.push({ kind: "tool_group", label: "Searching...", steps: [act.label] });
      } else {
        out.push(act);
      }
    }
    return out;
  }

  async function resolve(act, choice) {
    const res = await fetch(`${API_BASE}/api/memory/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conflict_id: act.id, choice, conversation_id: chatId }),
    });
    const data = await res.json();
    act.resolved = data.ok ? choice : "expired";
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
</script>

<svelte:window onclick={handleWindowClick} />

<section class="chat-window">
  <div class="window-header">
    <div class="menu-wrap" bind:this={menuWrap}>
      <Button kind="ghost" size="small" icon={OverflowMenuVertical} iconDescription="Chat options" onclick={() => (menuOpen = !menuOpen)} />
      {#if menuOpen}
        <div class="menu-popover">
          <button class="menu-item" onclick={handleClearChat}>
            <TrashCan size={16} /> Clear chat
          </button>
          <button class="menu-item" onclick={handleSplitPane}>
            <ColumnDependency size={16} /> Split pane
          </button>
        </div>
      {/if}
    </div>
  </div>

  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="stream" bind:this={scroller} onclick={handleStreamClick} onkeydown={handleStreamKeydown}>
    {#if session.messages.length === 0}
      <p class="empty">Say something. What you reveal about yourself gets remembered.</p>
    {/if}

    {#each session.messages as msg, idx}
      {#if msg.role === "user"}
        <div class="turn user"><div class="said">{msg.content}</div></div>
      {:else}
        <div class="turn assistant">
          {#if session.processing && idx === session.messages.length - 1}
            <div class="processing-container">
              <div class="typing-indicator"><span></span><span></span><span></span></div>
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
            {:else if act.kind === "commitment_resolution_request"}
              <CommitmentResolutionBlock {act} onResolve={(choice) => resolveCommitmentRequest(act, choice)} />
            {:else}
              <ActivityStrip {act} {chatId} />
            {/if}
          {/each}
        </div>
      {/if}
    {/each}
  </div>

  <div class="composer">
    <div class="composer-inner">
      {#if isEditingMemory}
        <div class="edit-banner">
          <span class="edit-banner-label">Editing memory</span>
          <button class="edit-banner-close" onclick={handleCancelEdit} aria-label="Cancel edit">
            <IconClose size={13} />
          </button>
        </div>
      {/if}
      <div class="composer-pill" class:multiline={isMultiline} class:editing={isEditingMemory} bind:this={composerEl}>
        <Button kind="ghost" size="small" icon={IconPlus} iconDescription="Attach file (coming soon)" disabled />
        <div class="editor-wrapper">
          <CodeMirror bind:value={session.input} extensions={editorExtensions} placeholder={isEditingMemory ? "Edit this memory..." : "Ask loki"} />
        </div>
        <Button kind="ghost" size="small" icon={IconMic} iconDescription="Voice input (coming soon)" disabled />
        <Button
          kind="primary" size="field"
          icon={session.streaming ? IconSpinner : isEditingMemory ? IconCheck : IconSend}
          iconDescription={session.streaming ? "Sending" : isEditingMemory ? "Save" : "Send"}
          disabled={session.streaming}
          onclick={() => handleSend()}
        />
      </div>
    </div>
  </div>
</section>

<style>
  .chat-window {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    height: 100%;
  }

  .window-header {
    display: flex;
    justify-content: flex-end;
    padding: 0.4rem 0.75rem;
    flex-shrink: 0;
  }
  .menu-wrap { position: relative; }
  .menu-popover {
    position: absolute;
    top: 100%;
    right: 0;
    margin-top: 0.25rem;
    background: var(--surface-card);
    border: 0.5px solid var(--border-hairline);
    border-radius: var(--radius-sm);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    z-index: 10;
    min-width: 140px;
    overflow: hidden;
  }
  .menu-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
    padding: 0.5rem 0.75rem;
    background: none;
    border: none;
    color: var(--text-primary);
    font-size: 0.85rem;
    text-align: left;
    cursor: pointer;
  }
  .menu-item:hover { background: var(--surface-sunken); }

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
    0%, 80%, 100% { transform: scale(0); opacity: 0.5; }
    40% { transform: scale(1); opacity: 1; }
  }

  .stream {
    flex: 1;
    overflow-y: auto;
    padding: 2rem 1.5rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1.6rem;
  }

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
  .prose :global(p) { margin: 0.6rem 0; }
  .prose :global(p:first-child) { margin-top: 0; }

  .prose :global(h1), .prose :global(h2), .prose :global(h3) {
    margin: 1.1rem 0 0.5rem;
    font-weight: 600;
    line-height: 1.3;
  }
  .prose :global(h1) { font-size: 1.25rem; }
  .prose :global(h2) { font-size: 1.1rem; }
  .prose :global(h3) { font-size: 1rem; }

  .prose :global(strong), .prose :global(b) {
    font-weight: 600;
    color: var(--text-primary);
  }

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
  .prose :global(ol > li) { margin: 0.35rem 0; }
  .prose :global(ol > li::marker) {
    color: var(--accent-memory);
    font-weight: 600;
  }

  .prose :global(a) { color: var(--accent-primary); }

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
  .prose :global(.citation:hover::after) { opacity: 1; }

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

  .prose :global(table) {
    width: 100%;
    border-collapse: collapse;
    margin: 1.2rem 0;
    font-size: 0.9rem;
    background: var(--surface-card);
    border-radius: var(--radius-sm);
    overflow: hidden;
  }
  .prose :global(th), .prose :global(td) {
    padding: 0.6rem 0.85rem;
    border: 0.5px solid var(--border-hairline);
    text-align: left;
  }
  .prose :global(th) {
    background: var(--surface-sunken);
    font-weight: 600;
    color: var(--text-primary);
  }
  .prose :global(tr:nth-child(even)) { background: var(--surface-veil); }

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
    padding: 1rem 1.5rem 1.4rem;
  }

  .composer-inner {
    width: 100%;
    max-width: 48rem;
  }

  .edit-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.4rem 0.9rem;
    margin-bottom: 0.35rem;
    background: var(--accent-primary-bg);
    border: 0.5px solid var(--border-hairline);
    border-radius: var(--radius-md);
  }
  .edit-banner-label {
    font-size: 0.78rem;
    color: var(--accent-primary-soft);
    font-weight: 600;
  }
  .edit-banner-close {
    display: flex;
    align-items: center;
    justify-content: center;
    background: none;
    border: none;
    color: var(--text-secondary);
    cursor: pointer;
    padding: 0.15rem;
    border-radius: var(--radius-sm);
  }
  .edit-banner-close:hover { color: var(--text-primary); background: var(--surface-sunken); }

  .composer-pill {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    width: 100%;
    padding: 0.4rem 0.4rem 0.4rem 0.6rem;
    background: var(--surface-card);
    border: 0.5px solid var(--border-hairline);
    border-radius: var(--radius-full);
    overflow: hidden;
    transition: border-radius var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
  }
  .composer-pill:focus-within {
    border-color: var(--accent-primary);
  }
  .composer-pill.editing {
    border-color: var(--accent-primary);
  }
  .composer-pill.multiline {
    border-radius: var(--radius-lg);
    align-items: flex-end;
  }

  .editor-wrapper {
    flex: 1;
    min-width: 0;
  }
  .editor-wrapper :global(.cm-editor) {
    background: transparent !important;
    color: var(--text-primary);
    font-family: inherit;
    font-size: 0.95rem;
    line-height: 1.5;
    border: none !important;
    outline: none !important;
    box-shadow: none !important;
  }
  .editor-wrapper :global(.cm-editor.cm-focused) {
    outline: none !important;
    box-shadow: none !important;
    border: none !important;
  }
  .editor-wrapper :global(.cm-scroller) {
    background: transparent !important;
    min-height: 1.8rem;
    max-height: 40vh;
    overflow-y: auto;
    padding: 0.3rem 0.2rem;
    box-sizing: border-box;
    font-family: var(--font-voice) !important;
  }
  .editor-wrapper :global(.cm-content) {
    background: transparent !important;
    caret-color: var(--text-primary);
    padding: 0;
  }
  .editor-wrapper :global(.cm-cursor) {
    border-left-color: var(--text-primary) !important;
    border-left-width: 1.5px !important;
  }
  .editor-wrapper :global(.cm-gutters) { display: none !important; }
  .editor-wrapper :global(.cm-activeLine) { background-color: transparent !important; }
</style>