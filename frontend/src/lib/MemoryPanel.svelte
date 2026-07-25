<script>
  let { memory, branch } = $props();
</script>

<aside class="panel">
  <div class="panel-head">
    <span class="meta">viewing — {branch}</span>
    <span class="count">{memory.length}</span>
  </div>

  {#if memory.length === 0}
    <p class="empty small">Nothing stored on this branch yet.</p>
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

<style>
  .panel {
    border-left: 1px solid var(--rule);
    overflow-y: auto;
    padding: 0.9rem 1rem 2rem;
    background: rgba(255, 255, 255, 0.35);
    height: 100%;
  }
  .panel-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding-bottom: 0.6rem;
    border-bottom: 1px solid var(--rule);
    margin-bottom: 0.9rem;
  }
  .meta {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.62rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--verdigris);
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
  .empty.small {
    color: var(--ink-soft);
    font-size: 0.8rem;
    font-style: italic;
    padding: 0 1rem;
  }
</style>