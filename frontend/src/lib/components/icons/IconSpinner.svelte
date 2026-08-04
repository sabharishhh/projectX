<script>
  let { size = 16 } = $props();
</script>
<svg class="spinner" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
  <circle cx="12" cy="12" r="9" stroke-opacity="0.25"></circle>
  <path d="M21 12a9 9 0 0 0-9-9"></path>
</svg>
<style>
  .spinner { animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>