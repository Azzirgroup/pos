<script setup>
import { state } from '../store'
import Icon from './Icon.vue'
</script>

<template>
	<div class="toasts" aria-live="polite">
		<TransitionGroup name="toast">
			<div v-for="t in state.toasts" :key="t.id" class="toast" :class="`toast-${t.tone}`">
				<Icon :name="t.tone === 'error' ? 'close' : 'check'" size="i-md" />
				<span>{{ t.message }}</span>
			</div>
		</TransitionGroup>
	</div>
</template>
