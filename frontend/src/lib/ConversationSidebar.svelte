<script>
  let { conversations, activeId, onNew, onSelect } = $props();
</script>

<aside class="sidebar">
  <div class="brand">projectX</div>
  <button class="new-chat" onclick={onNew}>+ New chat</button>

  <div class="list">
    {#if conversations.length === 0}
      <p class="empty">No conversations yet</p>
    {:else}
      {#each conversations as c}
        <button
          class="conv"
          class:active={c.conversation_id === activeId}
          onclick={() => onSelect(c.conversation_id)}
        >
          {c.label}
        </button>
      {/each}
    {/if}
  </div>
</aside>

<style>
  .sidebar {
    display: flex;
    flex-direction: column;
    border-right: 1px solid var(--rule);
    background: rgba(255, 255, 255, 0.35);
    height: 100%;
    overflow: hidden;
  }
  .brand {
    padding: 0.9rem 1rem;
    font-weight: 600;
    font-size: 0.95rem;
    letter-spacing: -0.01em;
    border-bottom: 1px solid var(--rule);
  }
  .new-chat {
    margin: 0.75rem;
    padding: 0.5rem 0.7rem;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.72rem;
    letter-spacing: 0.03em;
    text-align: left;
    background: var(--verdigris);
    color: var(--paper);
    border: none;
    border-radius: 3px;
    cursor: pointer;
  }
  .new-chat:hover {
    opacity: 0.9;
  }
  .list {
    flex: 1;
    overflow-y: auto;
    padding: 0 0.5rem 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }
  .conv {
    display: block;
    width: 100%;
    text-align: left;
    padding: 0.5rem 0.6rem;
    font-size: 0.82rem;
    line-height: 1.3;
    color: var(--ink-soft);
    background: none;
    border: none;
    border-radius: 3px;
    cursor: pointer;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .conv:hover {
    background: var(--wash);
    color: var(--ink);
  }
  .conv.active {
    background: var(--wash);
    color: var(--ink);
    font-weight: 600;
    border-left: 2px solid var(--verdigris);
    padding-left: calc(0.6rem - 2px);
  }
  .empty {
    padding: 0.6rem 0.75rem;
    font-size: 0.8rem;
    font-style: italic;
    color: var(--ink-soft);
  }
</style>