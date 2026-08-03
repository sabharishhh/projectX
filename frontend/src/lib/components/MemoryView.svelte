<script>
  import Button from './ui/Button.svelte';
  import Tag from './ui/Tag.svelte';
  import Edit from 'carbon-icons-svelte/lib/Edit.svelte';
  import TrashCan from 'carbon-icons-svelte/lib/TrashCan.svelte';
  import Collapsible from './Collapsible.svelte';
  import { reveal } from '../motion.js';

  let { memory = [], onopensource = () => {}, ondelete = () => {}, onedit = () => {}, oncreate = () => {} } = $props();

  let editingHash = $state(null);
  let editDraft = $state('');
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

  function startEdit(u) { editingHash = u.hash; editDraft = u.content; }
  function cancelEdit() { editingHash = null; editDraft = ''; }
  function saveEdit(u) {
    const trimmed = editDraft.trim();
    if (trimmed && trimmed !== u.content) onedit(u, trimmed);
    editingHash = null; editDraft = '';
  }
  function submitNewCommitment() {
    const trimmed = newCommitmentText.trim();
    if (!trimmed) return;
    oncreate(trimmed, newCommitmentDeadline || null);
    newCommitmentText = ''; newCommitmentDeadline = ''; showAddCommitment = false;
  }
</script>

<div class="memory-view">
  {#if grouped.length === 0}<p class="empty">Nothing remembered yet.</p>{/if}

  {#each grouped as group (group.type)}
    <div class="group">
      <Collapsible label={group.type} count={group.items.length} accent="var(--accent-primary)" open={group.type === 'identity'} boxed={false}>
        <ul>
          {#each group.items as u (u.hash)}
            <li in:reveal class:inferred={u.provenance === 'inferred'}>
              {#if editingHash === u.hash}
                <div class="edit-row">
                  <textarea class="edit-input" bind:value={editDraft} rows="2"
                    onkeydown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEdit(u); } if (e.key === 'Escape') cancelEdit(); }}
                  ></textarea>
                  <div class="edit-actions">
                    <Button size="small" kind="primary" onclick={() => saveEdit(u)}>Save</Button>
                    <Button size="small" kind="ghost" onclick={cancelEdit}>Cancel</Button>
                  </div>
                </div>
              {:else}
                <span class="content {u.provenance === 'inferred' ? 'provenance-inferred' : 'provenance-stated'}">{u.content}</span>
                <span class="item-actions">
                  {#if u.deadline}
                    <Tag type="warm-gray" size="sm">due {new Date(u.deadline).toLocaleDateString()}</Tag>
                  {:else}
                    <button class="source technical" title={u.source} onclick={() => onopensource(u.source)}>{u.hash.slice(0, 8)}</button>
                  {/if}
                  <button class="mini-btn" title="Edit" aria-label="Edit" onclick={() => startEdit(u)}><Edit size={14} /></button>
                  <button class="mini-btn danger" title="Delete" aria-label="Delete" onclick={() => ondelete(u)}><TrashCan size={14} /></button>
                </span>
              {/if}
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
  .mini-btn.danger:hover { color: var(--text-danger); background: var(--bg-danger); }
  .edit-row { grid-column: 1 / -1; display: flex; flex-direction: column; gap: var(--space-2); }
  .edit-input { width: 100%; box-sizing: border-box; font: inherit; font-size: var(--size-meta); padding: var(--space-2); border: 1px solid var(--accent-primary); border-radius: var(--radius-sm); background: var(--surface-page); color: var(--text-primary); resize: vertical; }
  .edit-actions { display: flex; gap: var(--space-2); }
  .empty { margin: 0; font-size: var(--size-meta); font-style: italic; color: var(--text-secondary); }
  .add-commitment { margin-top: var(--space-2); display: flex; flex-direction: column; gap: var(--space-2); }
  .add-input, .add-date { width: 100%; box-sizing: border-box; font: inherit; font-size: var(--size-meta); padding: var(--space-2); border: 1px solid var(--border-hairline); border-radius: var(--radius-sm); background: var(--surface-page); color: var(--text-primary); }
  .add-input:focus, .add-date:focus { border-color: var(--accent-primary); outline: none; }
</style>