<script>
  let { act } = $props();
</script>

{#if act.kind === "searching"}
  <div class="activity searching">{act.label}…</div>
{:else}
  <div class="activity {act.kind}">
    <button class="act-head" onclick={() => (act.open = !act.open)}>
      <span class="chev">{act.open ? "−" : "+"}</span>
      {act.label}
    </button>
    {#if act.open}
      <ul class="act-body">
        {#if act.kind === "search"}
          {#each act.results as r}
            <li>
              <a href={r.url} target="_blank" rel="noopener">{r.title}</a>
              <span class="method">via {r.extraction_method}</span>
              <span class="snippet">{r.summary}</span>
            </li>
          {/each}
        {:else}
          {#each act.units as u}
            <li>
              <span class="meta">{u.unit_type} · {u.provenance}</span>
              {u.content}
            </li>
          {/each}
        {/if}
      </ul>
    {/if}
  </div>
{/if}

<style>
  .activity {
    margin-top: 0.7rem;
    border: 1px dashed var(--verdigris);
    border-radius: 2px;
    background: var(--wash);
  }
  .activity.searching {
    padding: 0.4rem 0.6rem;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.7rem;
    color: var(--ink-soft);
    font-style: italic;
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
    padding: 0.35rem 0;
  }
  .act-body a {
    display: block;
    color: var(--verdigris);
    font-size: 0.85rem;
  }
  .method {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.6rem;
    color: #9aa39a;
    margin-left: 0.4rem;
  }
  .snippet {
    display: block;
    font-size: 0.8rem;
    color: var(--ink-soft);
    line-height: 1.4;
    margin-top: 0.15rem;
  }
  .meta {
    display: block;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.62rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--verdigris);
  }
</style>