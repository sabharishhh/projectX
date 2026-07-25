<script>
  import { arrive, reveal } from '$lib/motion.js';

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
    <p class="resolved" in:reveal>Noted — memory updated.</p>
  {:else}
    <div class="pair">
      <p class="was">was: {act.old.content}</p>
      <p class="now">now: {act.new.content}</p>
    </div>
    <div class="choices" class:busy>
      <button onclick={() => choose('update')} disabled={busy}>Replace it</button>
      <button onclick={() => choose('keep_both')} disabled={busy}>Both are true</button>
      <button onclick={() => choose('keep_old')} disabled={busy}>Ignore this</button>
    </div>
  {/if}
</section>

<style>
  .conflict {
    background:var(--surface-card); border:0.5px solid var(--border-strong);
    border-radius:var(--radius-lg); padding:var(--space-4); margin-block:var(--space-3);
  }
  .heading {
    display:flex; align-items:center; gap:var(--space-2); margin:0 0 var(--space-3);
    font-size:var(--size-meta); color:var(--accent-attention);
  }
  .pair { display:flex; flex-direction:column; gap:var(--space-2); margin-bottom:var(--space-4); }
  .was { margin:0; color:var(--text-muted); text-decoration:line-through; text-decoration-color:var(--text-muted); }
  .now { margin:0; color:var(--text-primary); }
  .choices { display:flex; gap:var(--space-2); transition:opacity var(--dur-fast) var(--ease-out); }
  .choices.busy { opacity:.5; pointer-events:none; }
  .choices button { flex:1; }
  .resolved { margin:0; font-size:var(--size-meta); color:var(--text-secondary); }
</style>