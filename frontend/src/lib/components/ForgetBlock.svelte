<script>
  let { act, onResolve } = $props();
</script>

<div class="activity forget">
  <div class="act-head static">{act.label}</div>
  <div class="forget-body">
    <p class="fact"><span class="meta">stored</span>{act.content}</p>
    {#if act.reason}
      <p class="reason">{act.reason}</p>
    {/if}

    {#if act.resolved}
      <p class="resolved">
        {act.resolved === "soft"
          ? "Forgotten — kept in history, no longer used."
          : act.resolved === "hard"
            ? "Permanently deleted."
            : act.resolved === "expired"
              ? "This request expired (server restarted since)."
              : "Kept."}
      </p>
    {:else}
      <div class="choices">
        <button onclick={() => onResolve("soft")}>Forget it</button>
        <button class="danger" onclick={() => onResolve("hard")}>Delete permanently</button>
        <button onclick={() => onResolve("cancel")}>Keep it</button>
      </div>
    {/if}
  </div>
</div>

<style>
  .activity.forget {
    margin-top: 0.7rem;
    border-radius: 2px;
    border: 1px solid #9c3b2e;
    background: #f2e4e1;
  }
  .act-head.static {
    padding: 0.4rem 0.6rem;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.7rem;
    letter-spacing: 0.03em;
    color: #9c3b2e;
  }
  .forget-body {
    padding: 0 0.7rem 0.6rem;
  }
  .forget-body p {
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
    color: #9c3b2e;
  }
  .reason {
    font-style: italic;
    color: var(--ink-soft);
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
    border: 1px solid #9c3b2e;
    border-radius: 2px;
    background: none;
    color: #9c3b2e;
    cursor: pointer;
  }
  .choices button:hover {
    background: #9c3b2e;
    color: #f2e4e1;
  }
  .choices button.danger {
    font-weight: 600;
  }
  .resolved {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.68rem;
    color: #9c3b2e;
    margin-top: 0.5rem;
  }
</style>