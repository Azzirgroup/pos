<script setup>
/** An order status as a small coloured label. */
defineProps({ status: String, large: Boolean })
const slug = (s) => (s || '').toLowerCase().replace(/\s+/g, '-')
</script>

<template>
	<span class="status-chip" :class="[`st-${slug(status)}`, { large }]"><span class="dot" />{{ status === 'Draft' ? 'In cart' : status }}</span>
</template>
