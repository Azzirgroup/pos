<script setup>
import { ref } from 'vue'
import AppRail from '@/components/AppRail.vue'
import AppTopBar from '@/components/AppTopBar.vue'
import ModuleTabs from '@/components/ModuleTabs.vue'
import { MODULE_TABS, moduleFor } from '@/data/navigation'
import { useBuildCheck } from '@/composables/useBuildCheck'
import { useRoute } from 'vue-router'
import { computed, watch } from 'vue'

// Three states, cycled by the top-bar toggle. Persisted because it is a
// per-user preference about screen space, not a per-visit choice.
const RAIL_MODES = ['icons', 'labels', 'hidden']
const railMode = ref(localStorage.getItem('cosmestics:rail') || 'icons')

/**
 * On a phone the rail is a drawer, not a column.
 *
 * It used to be `hidden md:flex` with the same toggle cycling its width, which
 * meant a phone had no navigation at all — the button was there, and pressing it
 * changed a setting for a column that was never rendered. So the toggle opens a
 * drawer below the md breakpoint and keeps cycling above it.
 */
const mobileNav = ref(false)
const isWide = () => window.matchMedia('(min-width: 768px)').matches

function cycleRail() {
	if (!isWide()) {
		mobileNav.value = !mobileNav.value
		return
	}
	const next = RAIL_MODES[(RAIL_MODES.indexOf(railMode.value) + 1) % RAIL_MODES.length]
	railMode.value = next
	localStorage.setItem('cosmestics:rail', next)
}
const route = useRoute()

/**
 * The module whose tab strip is showing.
 *
 * Held rather than derived fresh each time, so `moduleFor` can keep you where
 * you are when the page you opened belongs to your current module as well as
 * another one. Recomputed from the path alone whenever it does not.
 */
const currentModule = ref(null)

watch(
	() => route.path,
	(path) => {
		currentModule.value = moduleFor(path, currentModule.value)
		// Navigating is the whole point of the drawer, so it closes itself once
		// you do.
		mobileNav.value = false
	},
	{ immediate: true },
)

// Sub-tabs only where a module has more than one activity.
const moduleTabs = computed(() => MODULE_TABS[currentModule.value] || null)

// Notices when a deploy has happened under this tab. See the composable for
// why it offers a reload rather than performing one.
const { buildStale } = useBuildCheck()

// `window` is not in scope inside a template, so the reload is a handler.
function reloadApp() {
	window.location.reload()
}
</script>

<template>
	<!-- The shell never scrolls; only the routed view's inner panes do. That is
	     what keeps the pay button reachable on every screen. -->
	<div class="relative flex h-full flex-col overflow-hidden bg-surface-gray-1">
		<AppTopBar @toggle-rail="cycleRail" />

		<!-- A deploy happened while this tab was open, so it is running older code
		     than the server. Offered rather than forced: the cart lives in memory
		     and a surprise reload would take it with it. -->
		<div
			v-if="buildStale"
			class="flex shrink-0 items-center justify-center gap-3 bg-surface-amber-2 px-3 py-1.5 text-p-sm text-ink-amber-3"
		>
			<span>A newer version of the till is available.</span>
			<button
				class="rounded-md bg-surface-gray-7 px-2.5 py-1 text-p-xs font-semibold text-ink-white hover:bg-surface-gray-6"
				@click="reloadApp"
			>
				Reload
			</button>
		</div>

		<div class="flex min-h-0 flex-1 overflow-hidden">
			<AppRail v-if="railMode !== 'hidden'" :mode="railMode" class="hidden md:flex" />
			<div class="flex min-w-0 flex-1 flex-col overflow-hidden">
				<ModuleTabs v-if="moduleTabs" :tabs="moduleTabs" />
				<router-view />
			</div>
		</div>

		<!-- Phone navigation. Labelled rather than icon-only: there is room for
		     words in a drawer, and an icon a cashier has to decode is the reason
		     the rail is collapsed on a desk, not a virtue. -->
		<Transition
			enter-active-class="transition-opacity duration-150"
			leave-active-class="transition-opacity duration-150"
			enter-from-class="opacity-0"
			leave-to-class="opacity-0"
		>
			<div
				v-if="mobileNav"
				class="fixed inset-0 z-40 bg-black-overlay-200 md:hidden"
				@click="mobileNav = false"
			/>
		</Transition>
		<Transition
			enter-active-class="transition-transform duration-200"
			leave-active-class="transition-transform duration-200"
			enter-from-class="-translate-x-full"
			leave-to-class="-translate-x-full"
		>
			<AppRail
				v-if="mobileNav"
				mode="labels"
				class="fixed inset-y-0 left-0 z-40 shadow-xl md:hidden"
			/>
		</Transition>
	</div>
</template>
