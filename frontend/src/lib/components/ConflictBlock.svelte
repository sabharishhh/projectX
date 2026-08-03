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

<section class="conflict" in:arrive aria-live="polite">
  <p class="heading"><i class="ti ti-alert-circle" aria-hidden="true"></i>This changes something I already knew</p>

  {#if act.resolved === 'expired'}
    <p class="resolved" in:reveal>This one expired when the backend restarted. Tell me again and I'll store it.</p>
  {:else if act.resolved}
    <p class="resolved" in:reveal><i class="ti ti-check" aria-hidden="true"></i>Noted — memory updated.</p>
  {:else}
    <div class="pair">
      <p class="was">was: {act.old.content}</p>
      <p class="now">now: {act.new.content}</p>
    </div>
    <div class="choices" class:busy>
      <Button size="small" kind="primary" disabled={busy} onclick={() => choose('update')}>Replace it</Button>
      <Button size="small" kind="tertiary" disabled={busy} onclick={() => choose('keep_both')}>Both are true</Button>
      <Button size="small" kind="ghost" disabled={busy} onclick={() => choose('keep_old')}>Ignore this</Button>
    </div>
  {/if}
</section>

<style>
  .conflict {
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
  .pair { display: flex; flex-direction: column; gap: var(--space-2); margin-bottom: var(--space-4); }
  .pair p { margin: 0; padding: var(--space-2) var(--space-3); border-radius: var(--radius-sm); font-size: var(--size-meta); }
  .was { background: var(--surface-sunken); color: var(--text-muted); text-decoration: line-through; text-decoration-color: var(--text-muted); }
  .now { background: color-mix(in srgb, var(--accent-primary) 10%, transparent); color: var(--text-primary); }
  .choices { display: flex; gap: var(--space-2); transition: opacity var(--dur-fast) var(--ease-out); }
  .choices.busy { opacity: .5; }
  .resolved { display: flex; align-items: center; gap: var(--space-2); margin: 0; font-size: var(--size-meta); color: var(--text-secondary); }
</style>