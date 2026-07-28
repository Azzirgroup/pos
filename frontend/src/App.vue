<script setup>
import { ref } from 'vue'
import AppRail from '@/components/AppRail.vue'
import AppTopBar from '@/components/AppTopBar.vue'
import ModuleTabs from '@/components/ModuleTabs.vue'
import { MODULE_TABS, moduleFor } from '@/data/navigation'
import { useRoute } from 'vue-router'
import { computed } from 'vue'

// Three states, cycled by the top-bar toggle. Persisted because it is a
// per-user preference about screen space, not a per-visit choice.
const RAIL_MODES = ['icons', 'labels', 'hidden']
const railMode = ref(localStorage.getItem('cosmestics:rail') || 'icons')

function cycleRail() {
	const next = RAIL_MODES[(RAIL_MODES.indexOf(railMode.value) + 1) % RAIL_MODES.length]
	railMode.value = next
	localStorage.setItem('cosmestics:rail', next)
}
const route = useRoute()
// Sub-tabs only where a module has more than one activity.
const moduleTabs = computed(() => MODULE_TABS[moduleFor(route.path)] || null)
</script>

<template>
	<!-- The shell never scrolls; only the routed view's inner panes do. That is
	     what keeps the pay button reachable on every screen. -->
	<div class="relative flex h-full flex-col overflow-hidden bg-surface-gray-1">
		<AppTopBar @toggle-rail="cycleRail" />

		<div class="flex min-h-0 flex-1 overflow-hidden">
			<AppRail v-if="railMode !== 'hidden'" :mode="railMode" class="hidden md:flex" />
			<div class="flex min-w-0 flex-1 flex-col overflow-hidden">
				<ModuleTabs v-if="moduleTabs" :tabs="moduleTabs" />
				<router-view />
			</div>
		</div>
	</div>
</template>
