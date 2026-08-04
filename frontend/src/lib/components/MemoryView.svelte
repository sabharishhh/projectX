<script>
  import Button from './ui/Button.svelte';
  import Tag from './ui/Tag.svelte';
  import IconEdit from './icons/IconEdit.svelte';
  import IconTrash from './icons/IconTrash.svelte';
  import IconMoreVertical from './icons/IconMoreVertical.svelte';
  import IconFlag from './icons/IconFlag.svelte';
  import Collapsible from './Collapsible.svelte';
  import { reveal } from '../motion.js';
  import { beginMemoryEdit } from '../stores/workspace.svelte.ts';

  let { memory = [], onopensource = () => {}, ondelete = () => {}, oncreate = () => {} } = $props();

  let openMenuHash = $state(null);
  let showAddCommitment = $state(false);
  let newCommitmentText = $state('');
  let newCommitmentDeadline = $state('');

  const ORDER = ['identity', 'preference', 'project', 'decision', 'relationship', 'commitment', 'correction'];
  const grouped = $derived(
    ORDER.map((type) => ({
      type,
      items: memory.filter((u) =>
        u.unit_type === type && !(type === 'commitment' && u.commitment_status && u.commitment_status !== 'open')
      ),
    })).filter((g) => g.items.length || g.type === 'commitment')
  );

  function handleWindowClick(e) {
    if (openMenuHash && !e.target.closest('.item-menu')) openMenuHash = null;
  }

  function handleEdit(u) {
    openMenuHash = null;
    beginMemoryEdit(u);
  }

  function handleDelete(u) {
    openMenuHash = null;
    ondelete(u);
  }

  function submitNewCommitment() {
    const trimmed = newCommitmentText.trim();
    if (!trimmed) return;
    oncreate(trimmed, newCommitmentDeadline || null);
    newCommitmentText = ''; newCommitmentDeadline = ''; showAddCommitment = false;
  }
</script>

<svelte:window onclick={handleWindowClick} />

<div class="memory-view">
  {#if grouped.length === 0}<p class="empty">Nothing remembered yet.</p>{/if}

  {#each grouped as group (group.type)}
    <div class="group">
      <Collapsible label={group.type} count={group.items.length} accent="var(--accent-primary)" open={group.type === 'identity'} boxed={false}>
        <ul>
          {#each group.items as u (u.hash)}
            <li in:reveal class:inferred={u.provenance === 'inferred'}>
              <span class="content {u.provenance === 'inferred' ? 'provenance-inferred' : 'provenance-stated'}">{u.content}</span>
              <span class="item-actions">
                {#if u.deadline}
                  <Tag type="warm-gray" size="sm">due {new Date(u.deadline).toLocaleDateString()}</Tag>
                {:else}
                  <button class="source technical" title={u.source} onclick={() => onopensource(u.source)}>{u.hash.slice(0, 8)}</button>
                {/if}
                <div class="item-menu">
                  <button class="mini-btn" title="Options" aria-label="Options" onclick={() => (openMenuHash = openMenuHash === u.hash ? null : u.hash)}>
                    <IconMoreVertical size={14} />
                  </button>
                  {#if openMenuHash === u.hash}
                    <div class="item-menu-popover">
                      <button class="menu-item" onclick={() => handleEdit(u)}>
                        <IconEdit size={14} /> Edit
                      </button>
                      <button class="menu-item" onclick={() => handleDelete(u)}>
                        <IconTrash size={14} /> Delete
                      </button>
                      <button class="menu-item disabled" disabled title="Coming soon">
                        <IconFlag size={14} /> Mark not relevant
                      </button>
                    </div>
                  {/if}
                </div>
              </span>
            </li>
          {/each}
        </ul>

        {#if group.type === 'commitment'}
          <div class="add-commitment">
            {#if showAddCommitment}
              <input type="text" class="add-input" placeholder="What do you need to do?" bind:value={newCommitmentText} />
              <input type="date" class="add-date" bind:value={newCommitmentDeadline} title="Leave blank for no due date" />
              <div class="edit-actions">
                <Button size="small" kind="primary" onclick={submitNewCommitment}>Add</Button>
                <Button size="small" kind="ghost" onclick={() => (showAddCommitment = false)}>Cancel</Button>
              </div>
            {:else}
              <Button size="small" kind="tertiary" onclick={() => (showAddCommitment = true)}>+ Add commitment</Button>
            {/if}
          </div>
        {/if}
      </Collapsible>
    </div>
  {/each}
</div>

<style>
  .memory-view { display: flex; flex-direction: column; }
  .group + .group { margin-top: var(--space-3); padding-top: var(--space-2); border-top: 1px solid var(--border-hairline); }
  ul { list-style: none; margin: 0; padding: 0; }
  li {
    display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: var(--space-3); align-items: baseline;
    padding: var(--space-3) 0 var(--space-3) var(--space-3); border-left: 2px solid var(--accent-primary);
    font-size: var(--size-meta); line-height: var(--leading-body);
  }
  li.inferred { border-left-color: var(--text-muted); }
  li + li { margin-top: var(--space-2); }
  .content { min-width: 0; overflow-wrap: anywhere; }
  .item-actions { display: flex; align-items: center; gap: var(--space-2); flex-shrink: 0; }
  .source { border: 0; padding: 0; background: none; color: var(--text-muted); font-family: var(--font-technical); font-size: var(--size-caption); cursor: pointer; }
  .source:hover { color: var(--accent-primary); }
  .mini-btn { display: inline-flex; border: 0; padding: 0.2rem; background: none; color: var(--text-muted); border-radius: var(--radius-sm); cursor: pointer; }
  .mini-btn:hover { background: var(--surface-sunken); color: var(--text-primary); }

  .item-menu { position: relative; }
  .item-menu-popover {
    position: absolute;
    top: 100%;
    right: 0;
    margin-top: 0.25rem;
    background: var(--surface-card);
    border: 0.5px solid var(--border-hairline);
    border-radius: var(--radius-sm);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    z-index: 10;
    min-width: 160px;
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
    font-size: 0.82rem;
    text-align: left;
    cursor: pointer;
  }
  .menu-item:hover { background: var(--surface-sunken); }
  .menu-item.disabled { color: var(--text-muted); cursor: default; }
  .menu-item.disabled:hover { background: none; }

  .edit-actions { display: flex; gap: var(--space-2); }
  .empty { margin: 0; font-size: var(--size-meta); font-style: italic; color: var(--text-secondary); }
  .add-commitment { margin-top: var(--space-2); display: flex; flex-direction: column; gap: var(--space-2); }
  .add-input, .add-date { width: 100%; box-sizing: border-box; font: inherit; font-size: var(--size-meta); padding: var(--space-2); border: 1px solid var(--border-hairline); border-radius: var(--radius-sm); background: var(--surface-page); color: var(--text-primary); }
  .add-input:focus, .add-date:focus { border-color: var(--accent-primary); outline: none; }
</style>