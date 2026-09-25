<script setup>
/** An icon from the page's sprite (rendered by base.html). */
defineProps({ name: { type: String, required: true }, size: { type: String, default: 'i' } })
</script>

<template>
	<svg :class="size" aria-hidden="true"><use :href="`#i-${name}`" /></svg>
</template>
