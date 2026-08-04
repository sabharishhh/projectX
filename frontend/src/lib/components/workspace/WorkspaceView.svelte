<script>
  import Pane from "./Pane.svelte";
  import { workspace, dragState, dropChatIntoNewPane } from "../../stores/workspace.svelte.ts";

  let isDragOver = $state(false);

  function handleDrop(e) {
    e.preventDefault();
    isDragOver = false;
    const chatId = e.dataTransfer.getData('text/plain');
    if (chatId) dropChatIntoNewPane(chatId);
  }
</script>

<div class="workspace" style:grid-template-columns={`repeat(${workspace.panes.length}, 1fr)`}>
  {#each workspace.panes as pane (pane.id)}<Pane {pane} />{/each}

  {#if dragState.active && workspace.panes.length < 3}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="new-pane-zone"
      class:drag-over={isDragOver}
      ondragover={(e) => { e.preventDefault(); isDragOver = true; }}
      ondragleave={() => (isDragOver = false)}
      ondrop={handleDrop}
    >
      <span>Drop to split</span>
    </div>
  {/if}
</div>

<style>
  .workspace { display: grid; height: 100%; gap: 1px; background: var(--border-hairline); position: relative; }

  .new-pane-zone {
    position: absolute;
    top: 0; right: 0; bottom: 0;
    width: 64px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: color-mix(in srgb, var(--accent-primary) 6%, var(--surface-page));
    border-left: 2px dashed var(--border-strong);
    z-index: 6;
    writing-mode: vertical-rl;
    color: var(--text-muted);
    font-size: 0.75rem;
    letter-spacing: 0.02em;
    transition: background var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
  }
  .new-pane-zone.drag-over {
    background: color-mix(in srgb, var(--accent-primary) 16%, var(--surface-page));
    border-left-color: var(--accent-primary);
    color: var(--accent-primary);
  }
</style>