<script>
  import Button from './ui/Button.svelte';
  import { arrive, reveal } from '../motion.js';

  let { act, onResolve } = $props();
  let busy = $state(false);

  async function choose(choice) {
    busy = true;
    await onResolve(choice);
    busy = false;
  }
</script>

<section class="forget" in:arrive aria-live="polite">
  <p class="heading"><i class="ti ti-eraser" aria-hidden="true"></i>{act.label}</p>

  {#if act.resolved}
    <p class="resolved" in:reveal>
      <i class="ti {act.resolved === 'cancel' ? 'ti-check' : 'ti-eraser'}" aria-hidden="true"></i>
      {act.resolved === 'soft'
        ? 'Forgotten — kept in history, no longer used.'
        : act.resolved === 'hard'
          ? 'Permanently deleted.'
          : act.resolved === 'expired'
            ? 'This request expired (server restarted since).'
            : 'Kept.'}
    </p>
  {:else}
    <div class="fact-card">
      <span class="meta technical">stored</span>
      <p class="content">{act.content}</p>
    </div>
    {#if act.reason}<p class="reason">{act.reason}</p>{/if}

    <div class="choices" class:busy>
      <Button size="small" kind="tertiary" disabled={busy} onclick={() => choose('soft')}>Forget it</Button>
      <Button size="small" kind="danger" disabled={busy} onclick={() => choose('hard')}>Delete permanently</Button>
      <Button size="small" kind="ghost" disabled={busy} onclick={() => choose('cancel')}>Keep it</Button>
    </div>
  {/if}
</section>

<style>
  .forget {
    background: var(--surface-card);
    border: 1px solid var(--border-strong);
    border-left: 3px solid var(--accent-attention);
    border-radius: var(--radius-lg);
    padding: var(--space-4);
    margin-block: var(--space-3);
  }
  .heading {
    display: flex; align-items: center; gap: var(--space-2);
    margin: 0 0 var(--space-3);
    font-size: var(--size-meta); font-weight: var(--weight-semibold);
    color: var(--accent-attention);
  }
  .fact-card {
    background: var(--surface-sunken); border-radius: var(--radius-sm);
    padding: var(--space-2) var(--space-3); margin-bottom: var(--space-2);
  }
  .meta { display: block; text-transform: uppercase; letter-spacing: 0.08em; font-size: var(--size-caption); color: var(--text-muted); margin-bottom: 2px; }
  .content { margin: 0; font-size: var(--size-meta); line-height: var(--leading-tight); color: var(--text-primary); }
  .reason { margin: 0 0 var(--space-3); font-size: var(--size-meta); font-style: italic; color: var(--text-secondary); }
  .choices { display: flex; gap: var(--space-2); transition: opacity var(--dur-fast) var(--ease-out); }
  .choices.busy { opacity: .5; }
  .resolved { display: flex; align-items: center; gap: var(--space-2); margin: 0; font-size: var(--size-meta); color: var(--text-secondary); }
</style>