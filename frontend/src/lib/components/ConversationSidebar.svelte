<script>
  import { startChatDrag, endChatDrag } from '../stores/workspace.svelte.ts';
  
  let { conversations, activeId, onNew, onSelect, onDelete, onToggle } = $props();
</script>

<aside class="sidebar">
  <div class="brand-row">
    <div class="brand">Loki /.</div>
    <button class="icon-btn" onclick={onToggle} title="Close sidebar" aria-label="Close sidebar">
      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
        <line x1="9" y1="3" x2="9" y2="21"></line>
      </svg>
    </button>
  </div>
  
  <button class="new-chat" onclick={onNew}>+ New chat</button>

  <div class="list">
    {#if conversations.length === 0}
      <p class="empty">No conversations yet</p>
    {:else}
      {#each conversations as c}
        <div class="row" class:active={c.conversation_id === activeId}>
          <button
            class="conv"
            draggable="true"
            ondragstart={(e) => { e.dataTransfer.setData('text/plain', c.conversation_id); e.dataTransfer.effectAllowed = 'copy'; startChatDrag(c.conversation_id); }}
            ondragend={endChatDrag}
            onclick={() => onSelect(c.conversation_id)}
          >
            {c.label}
          </button>
          <button
            class="delete-btn"
            title="Delete this conversation"
            onclick={(e) => {
              e.stopPropagation();
              onDelete(c.conversation_id);
            }}
          >
            ×
          </button>
        </div>
      {/each}
    {/if}
  </div>
</aside>

<style>
  .sidebar {
    display: flex;
    flex-direction: column;
    border-right: 0.5px solid var(--border-hairline);
    background: var(--surface-veil);
    height: 100%;
    overflow: hidden;
  }
  
  .brand-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.6rem 0.6rem 0.6rem 1rem;
    border-bottom: 0.5px solid var(--border-hairline);
  }
  
  .brand {
    font-weight: 600;
    font-size: 0.95rem;
    letter-spacing: -0.01em;
  }

  .icon-btn svg {
    width: 1.25rem;
    height: 1.25rem;
    flex-shrink: 0;
  }
  
  .icon-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    height: 2rem;
    padding: 0;
    background: none;
    border: none;
    color: var(--text-secondary);
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  
  .icon-btn:hover {
    background: var(--surface-sunken);
    color: var(--text-primary);
  }

  .new-chat {
    margin: 0.75rem;
    padding: 0.5rem 0.7rem;
    font-family: var(--font-technical);
    font-size: 0.72rem;
    letter-spacing: 0.03em;
    text-align: left;
    background: var(--accent-memory);
    color: var(--surface-page);
    border: none;
    border-radius: var(--radius-sm);
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
  .row {
    display: flex;
    align-items: center;
    border-radius: var(--radius-sm);
  }
  .row:hover {
    background: var(--surface-sunken);
  }
  .row.active {
    background: var(--surface-sunken);
    border-left: 2px solid var(--accent-memory);
  }
  .conv {
    flex: 1;
    display: block;
    min-width: 0;
    text-align: left;
    padding: 0.5rem 0.6rem;
    font-size: 0.82rem;
    line-height: 1.3;
    color: var(--text-secondary);
    background: none;
    border: none;
    cursor: grab;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .row.active .conv {
    color: var(--text-primary);
    font-weight: 600;
  }
  .delete-btn {
    flex-shrink: 0;
    width: 1.4rem;
    height: 1.4rem;
    margin-right: 0.3rem;
    display: none;
    align-items: center;
    justify-content: center;
    font-size: 0.95rem;
    line-height: 1;
    color: var(--text-secondary);
    background: none;
    border: none;
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .row:hover .delete-btn {
    display: flex;
  }
  .delete-btn:hover {
    color: var(--text-danger);
    background: var(--bg-danger);
  }
  .empty {
    padding: 0.6rem 0.75rem;
    font-size: 0.8rem;
    font-style: italic;
    color: var(--text-secondary);
  }
</style>