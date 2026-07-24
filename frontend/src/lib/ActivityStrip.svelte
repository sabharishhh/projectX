<script>
  let { act, onResolve } = $props();
</script>

<div class="activity conflict">
  <div class="act-head static">{act.label}</div>
  <div class="conflict-body">
    <p class="was"><span class="meta">stored</span>{act.old.content}</p>
    <p class="now"><span class="meta">just now</span>{act.new.content}</p>

    {#if act.resolved}
      <p class="resolved">
        {act.resolved === "update"
          ? "Updated."
          : act.resolved === "keep_both"
            ? "Keeping both."
            : act.resolved === "expired"
              ? "This decision expired (server restarted since) — check current memory."
              : "Kept the original."}
      </p>
    {:else}
      <div class="choices">
        <button onclick={() => onResolve("update")}>Replace it</button>
        <button onclick={() => onResolve("keep_both")}>Both are true</button>
        <button onclick={() => onResolve("keep_old")}>Ignore this</button>
      </div>
    {/if}
  </div>
</div>

<style>
  .activity.conflict {
    margin-top: 0.7rem;
    border-radius: 2px;
    border: 1px solid #b07d2b;
    background: #f6efe0;
  }
  .act-head.static {
    padding: 0.4rem 0.6rem;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.7rem;
    letter-spacing: 0.03em;
    color: #8a5f1c;
  }
  .conflict-body {
    padding: 0 0.7rem 0.6rem;
  }
  .conflict-body p {
    margin: 0.3rem 0;
    font-size: 0.86rem;
    line-height: 1.45;
  }
  .meta {
    display: block;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.62rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #8a5f1c;
  }
  .was {
    opacity: 0.65;
  }
  .choices {
    display: flex;
    gap: 0.4rem;
    margin-top: 0.6rem;
  }
  .choices button {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.68rem;
    padding: 0.3rem 0.6rem;
    border: 1px solid #b07d2b;
    border-radius: 2px;
    background: none;
    color: #8a5f1c;
    cursor: pointer;
  }
  .choices button:hover {
    background: #b07d2b;
    color: #f6efe0;
  }
  .resolved {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.68rem;
    color: #8a5f1c;
    margin-top: 0.5rem;
  }
</style>