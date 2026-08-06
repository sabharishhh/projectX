<script>
  import { reveal } from '../motion.js';

  let { act } = $props();
  let open = $state(false);
</script>

<div class="trace">
  <button class="trace-trigger" onclick={() => (open = !open)} aria-expanded={open}>
    <span class="dot"></span>
    <span class="trace-label">{act.label}</span>
    <svg class="chevron" class:open viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
      <path d="M3 4.5 6 7.5 9 4.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  </button>

  {#if open}
    <div class="trace-detail" transition:reveal={{ duration: 180 }}>
      {#each act.units ?? [] as u}
        <p class="trace-line indent">
          {u.content}
          {#if u.unit_type === 'commitment' && u.commitment_status && u.commitment_status !== 'open'}
            <span class="muted">— {u.commitment_status}</span>
          {:else if u.deadline}
            <span class="muted">— due {new Date(u.deadline).toLocaleDateString()}</span>
          {/if}
        </p>
      {/each}
    </div>
  {/if}
</div>

<style>
  .trace { margin: 0 0 var(--space-4); }

  .trace-trigger {
    display: flex; align-items: center; gap: var(--space-2);
    background: none; border: none; padding: 0;
    cursor: pointer;
    color: var(--text-muted);
    font-size: var(--size-caption);
  }
  .trace-trigger:hover { color: var(--text-secondary); }
  .trace-trigger:hover .chevron { opacity: 1; }

  .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent-primary); flex-shrink: 0; }

  .trace-label { line-height: 1.4; }

  .chevron { opacity: 0.5; transition: transform var(--dur-fast) var(--ease-out), opacity var(--dur-fast) var(--ease-out); }
  .chevron.open { transform: rotate(180deg); }

  .trace-detail {
    margin-top: var(--space-2);
    padding-left: calc(6px + var(--space-2));
    display: flex; flex-direction: column; gap: 2px;
  }

  .trace-line {
    margin: 0;
    font-size: var(--size-caption); color: var(--text-secondary); line-height: 1.5;
  }
  .trace-line.indent { padding-left: 17px; color: var(--text-muted); }
  .trace-line .muted { color: var(--text-muted); }
</style>