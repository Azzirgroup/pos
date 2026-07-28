<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getMe } from '@/data/api'
import LucidePanelLeft from '~icons/lucide/panel-left'
import LucideZap from '~icons/lucide/zap'
import LucideChevronsUpDown from '~icons/lucide/chevrons-up-down'

const emit = defineEmits(['toggleRail'])

const route = useRoute()
const title = computed(() => route.meta?.title || 'POS')

// The signed-in account, not a hardcoded label: this is what a cashier checks
// before opening a shift, since the sale is recorded against it.
const me = ref(null)
const displayName = computed(() => me.value?.full_name || 'Loading…')
const initials = computed(() => me.value?.initials || '··')


onMounted(async () => {
	try {
		me.value = await getMe()
	} catch {
		// Never block the till on this; the corner just stays generic.
		me.value = { full_name: 'Signed in', initials: '··' }
	}
})


</script>

<template>
	<header
		class="relative flex h-11 shrink-0 items-center gap-2 border-b border-outline-gray-2 bg-surface-white px-2.5"
	>
		<button
			class="grid h-7 w-7 place-items-center rounded-md text-ink-gray-6 transition-colors hover:bg-surface-gray-2"
			aria-label="Toggle sidebar"
			@click="emit('toggleRail')"
		>
			<LucidePanelLeft class="h-[17px] w-[17px]" />
		</button>

		<div
			class="grid h-6 w-6 place-items-center rounded-full border border-outline-gray-2 text-ink-gray-7"
		>
			<LucideZap class="h-3 w-3" />
		</div>

		<span class="text-p-sm font-medium text-ink-gray-8">{{ title }}</span>

		<div class="ml-auto flex items-center gap-2">
			<div
				class="grid h-6 w-6 place-items-center rounded-full bg-surface-gray-7 text-[10px] font-semibold text-ink-white"
				:title="me?.user"
			>
				{{ initials }}
			</div>
			<span class="hidden max-w-[160px] truncate text-p-sm text-ink-gray-7 sm:block">
				{{ displayName }}
			</span>
			<LucideChevronsUpDown class="h-3.5 w-3.5 text-ink-gray-5" />
		</div>
	</header>
</template>
