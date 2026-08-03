<script>
  import Tag from './ui/Tag.svelte';
  import Link from 'carbon-icons-svelte/lib/Link.svelte';
  import Notebook from 'carbon-icons-svelte/lib/Notebook.svelte';
  import { reveal } from '../motion.js';

  let { messages = [] } = $props();

  const externalSources = $derived.by(() => {
    const seen = new Map();
    for (const msg of messages) {
      for (const act of msg.activity ?? []) {
        if (act.kind === 'source' && act.url && !seen.has(act.url)) {
          seen.set(act.url, { url: act.url, title: act.preview?.split(' — ')[0] || act.url, preview: act.preview });
        } else if (act.kind === 'search' && act.results?.length) {
          for (const r of act.results) {
            if (!seen.has(r.url)) seen.set(r.url, { url: r.url, title: r.title, preview: r.summary });
          }
        }
      }
    }
    return [...seen.values()];
  });

  const memoryReferences = $derived.by(() => {
    const seen = new Map();
    for (const msg of messages) {
      for (const act of msg.activity ?? []) {
        if ((act.kind === 'memory_read' || act.kind === 'time_travel') && act.units?.length) {
          for (const u of act.units) if (!seen.has(u.hash)) seen.set(u.hash, u);
        }
      }
    }
    return [...seen.values()];
  });
</script>

<div class="sources-view">
  <section>
    <div class="section-head">
      <Link size={16} />
      <h3>External resources</h3>
      <Tag type="gray" size="sm">{externalSources.length}</Tag>
    </div>
    {#if externalSources.length === 0}
      <div class="empty-card">No external searches yet this conversation.</div>
    {:else}
      <ul class="source-list">
        {#each externalSources as s (s.url)}
          <li in:reveal>
            <a href={s.url} target="_blank" rel="noreferrer"><span class="title">{s.title}</span></a>
            {#if s.preview}<p class="preview">{s.preview}</p>{/if}
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <section>
    <div class="section-head">
      <Notebook size={16} />
      <h3>Memory referenced</h3>
      <Tag type="gray" size="sm">{memoryReferences.length}</Tag>
    </div>
    {#if memoryReferences.length === 0}
      <div class="empty-card">No memory recalled yet this conversation.</div>
    {:else}
      <ul class="source-list">
        {#each memoryReferences as u (u.hash)}
          <li in:reveal>
            <div class="mem-ref">
              <Notebook size={14} />
              <span class="title">{u.content}</span>
            </div>
            <div class="mem-meta">
              <Tag type="cool-gray" size="sm">{u.unit_type}</Tag>
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  </section>
</div>

<style>
  .sources-view { display: flex; flex-direction: column; gap: var(--space-6); }
  .section-head { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-3); color: var(--accent-primary); }
  .section-head h3 { margin: 0; flex: 1; font-family: var(--font-display); font-size: var(--size-title); font-weight: var(--weight-semibold); color: var(--text-primary); }

  .empty-card {
    border: 1px dashed var(--border-strong); border-radius: var(--radius-md);
    padding: var(--space-4); text-align: center;
    font-size: var(--size-meta); color: var(--text-secondary); font-style: italic;
  }

  .source-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-2); }
  .source-list li { padding: var(--space-3); background: var(--surface-sunken); border-radius: var(--radius-md); }
  .source-list a { color: var(--accent-primary); font-size: var(--size-meta); text-decoration: none; }
  .source-list a:hover { text-decoration: underline; }
  .preview { margin: var(--space-1) 0 0; color: var(--text-secondary); font-size: var(--size-caption); line-height: var(--leading-tight); }
  .title { color: var(--text-primary); font-size: var(--size-meta); }
  .mem-ref { display: flex; align-items: flex-start; gap: var(--space-2); color: var(--text-primary); font-size: var(--size-meta); line-height: var(--leading-body); }
  .mem-ref :global(svg) { flex-shrink: 0; margin-top: 2px; color: var(--text-muted); }
  .mem-meta { display: flex; align-items: center; gap: var(--space-2); margin-top: var(--space-2); margin-left: calc(14px + var(--space-2)); }
</style>