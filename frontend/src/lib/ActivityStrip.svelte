<script>
  let { act } = $props();
</script>

<div class="activity {act.kind}">
  <button class="act-head" onclick={() => (act.open = !act.open)}>
    <span class="chev">{act.open ? "−" : "+"}</span>
    {act.label}
  </button>
  {#if act.open}
    {#if act.kind === "search"}
      <ul class="act-body">
        {#each act.results as r}
          <li>
            <a href={r.url} target="_blank" rel="noopener">{r.title}</a>
            <span class="snippet">{r.snippet}</span>
          </li>
        {/each}
      </ul>
    {:else}
      <ul class="act-body">
        {#each act.units as u}
          <li>
            <span class="meta">{u.unit_type} · {u.provenance}</span>
            {u.content}
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</div>

<style>
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
  .act-body a {
    color: var(--verdigris);
    font-size: 0.85rem;
  }
  .snippet {
    display: block;
    font-size: 0.78rem;
    color: var(--ink-soft);
    line-height: 1.4;
    margin-top: 0.15rem;
  }
</style>