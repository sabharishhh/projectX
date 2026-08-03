<script>
  let { small = false, description = 'Loading' } = $props();
</script>

<svg class="spinner" class:small viewBox="0 0 24 24" role="status" aria-label={description}>
  <circle class="track" cx="12" cy="12" r="9" fill="none" stroke-width="2.5" />
  <circle class="head" cx="12" cy="12" r="9" fill="none" stroke-width="2.5" stroke-linecap="round" />
</svg>

<style>
  .spinner { width: 20px; height: 20px; animation: spin 0.8s linear infinite; }
  .spinner.small { width: 16px; height: 16px; }
  .track { stroke: color-mix(in srgb, currentColor 20%, transparent); }
  .head { stroke: currentColor; stroke-dasharray: 42; stroke-dashoffset: 32; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>