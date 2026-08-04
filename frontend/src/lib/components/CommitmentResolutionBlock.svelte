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

<section class="commitment-resolution" in:arrive aria-live="polite">
  <p class="heading"><i class="ti ti-checklist" aria-hidden="true"></i>{act.label}</p>

  {#if act.resolved}
    <p class="resolved" in:reveal>
      <i class="ti {act.resolved === 'confirm' ? 'ti-check' : 'ti-arrow-back'}" aria-hidden="true"></i>
      {act.resolved === 'confirm'
        ? `Marked ${act.status}.`
        : act.resolved === 'expired'
          ? 'This request expired (server restarted since).'
          : 'Kept open.'}
    </p>
  {:else}
    <div class="fact-card">
      <span class="meta technical">{act.status === 'done' ? 'proposed done' : 'proposed cancelled'}</span>
      <p class="content">{act.content}</p>
    </div>

    <div class="choices" class:busy>
      <Button size="small" kind="primary" disabled={busy} onclick={() => choose('confirm')}>Confirm</Button>
      <Button size="small" kind="ghost" disabled={busy} onclick={() => choose('deny')}>Keep open</Button>
    </div>
  {/if}
</section>

<style>
  .commitment-resolution {
    background: var(--surface-card);
    border: 1px solid var(--border-strong);
    border-left: 3px solid var(--accent-primary);
    border-radius: var(--radius-lg);
    padding: var(--space-4);
    margin-block: var(--space-3);
  }
  .heading {
    display: flex; align-items: center; gap: var(--space-2);
    margin: 0 0 var(--space-3);
    font-size: var(--size-meta); font-weight: var(--weight-semibold);
    color: var(--accent-primary);
  }
  .fact-card {
    background: var(--surface-sunken); border-radius: var(--radius-sm);
    padding: var(--space-2) var(--space-3); margin-bottom: var(--space-2);
  }
  .meta { display: block; text-transform: uppercase; letter-spacing: 0.08em; font-size: var(--size-caption); color: var(--text-muted); margin-bottom: 2px; }
  .content { margin: 0; font-size: var(--size-meta); line-height: var(--leading-tight); color: var(--text-primary); }
  .choices { display: flex; gap: var(--space-2); transition: opacity var(--dur-fast) var(--ease-out); }
  .choices.busy { opacity: .5; }
  .resolved { display: flex; align-items: center; gap: var(--space-2); margin: 0; font-size: var(--size-meta); color: var(--text-secondary); }
</style>