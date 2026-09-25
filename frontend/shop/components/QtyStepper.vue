<script setup>
/** − 2 + with a ceiling: never more than the shop can sell. */
const props = defineProps({
	modelValue: { type: Number, required: true },
	max: { type: Number, default: 99 },
	min: { type: Number, default: 1 },
	busy: { type: Boolean, default: false },
	small: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
const set = (v) => emit('update:modelValue', Math.max(props.min, Math.min(props.max, v)))
</script>

<template>
	<div class="stepper" :class="{ 'is-small': small, 'is-busy': busy }">
		<button type="button" :disabled="busy || modelValue <= min" aria-label="Fewer" @click="set(modelValue - 1)">−</button>
		<span aria-live="polite">{{ modelValue }}</span>
		<button type="button" :disabled="busy || modelValue >= max" aria-label="More" @click="set(modelValue + 1)">+</button>
	</div>
</template>
