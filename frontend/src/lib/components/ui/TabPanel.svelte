<script>
  let { index, selected, children } = $props();
</script>

{#if selected === index}
  <div role="tabpanel" id="panel-{index}" aria-labelledby="tab-{index}" tabindex="0">
    {@render children?.()}
  </div>
{/if}