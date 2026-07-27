<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import LucideSearch from '~icons/lucide/search'
import LucideX from '~icons/lucide/x'
import LucideScanLine from '~icons/lucide/scan-line'
import LucideMenu from '~icons/lucide/menu'

const props = defineProps({
	modelValue: { type: String, default: '' },
	heldCount: { type: Number, default: 0 },
	/** Incrementing counter — each bump replays the confirmation pulse. */
	scanFlash: { type: Number, default: 0 },
	/** Open shift, or null. Drives the till indicator. */
	shift: { type: Object, default: null },
	/** Whether this browser can scan with the camera. */
	cameraScan: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'openHeld', 'openShift', 'openScanner', 'openMenu'])

const input = ref(null)

const query = computed({
	get: () => props.modelValue,
	set: (v) => emit('update:modelValue', v),
})

function focus() {
	input.value?.focus()
	input.value?.select()
}

function clear() {
	query.value = ''
	nextTick(focus)
}

defineExpose({ focus, clear })

// Brief green pulse on the scan icon confirms a scanner read landed, without
// stealing the cashier's attention with a toast.
const flashing = ref(false)
watch(
	() => props.scanFlash,
	() => {
		flashing.value = true
		setTimeout(() => (flashing.value = false), 400)
	},
)
</script>

<template>
	<header
		class="pt-safe flex shrink-0 items-center gap-2 border-b border-outline-gray-2 bg-surface-white px-3 py-2.5 sm:gap-3 sm:px-4"
	>
		<!-- Brand mark. Hidden below sm so search gets the full width on a phone. -->
		<div class="hidden shrink-0 items-center gap-2 sm:flex">
			<div
				class="grid h-9 w-9 place-items-center rounded-lg bg-surface-gray-7 text-p-sm font-semibold text-ink-white"
			>
				CO
			</div>
			<!-- Shift state doubles as the shop identity: a closed till is a
			     condition the cashier must notice before selling. -->
			<button
				class="hidden rounded-lg px-2 py-1 text-left leading-tight transition-colors hover:bg-surface-gray-2 lg:block"
				@click="emit('openShift')"
			>
				<div class="text-p-sm font-semibold text-ink-gray-9">Cosmestics</div>
				<div class="flex items-center gap-1.5 text-p-xs">
					<span
						class="h-1.5 w-1.5 rounded-full"
						:class="shift ? 'bg-surface-green-3' : 'bg-surface-gray-4'"
					/>
					<span :class="shift ? 'text-ink-green-3' : 'text-ink-gray-5'">
						{{ shift ? shift.pos_profile : 'Shift closed' }}
					</span>
				</div>
			</button>
		</div>

		<!-- Search is the primary control on this screen, so it takes the space. -->
		<div class="relative min-w-0 flex-1">
			<LucideSearch
				class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-gray-5"
			/>
			<input
				ref="input"
				v-model="query"
				type="text"
				inputmode="search"
				autocomplete="off"
				autocorrect="off"
				spellcheck="false"
				placeholder="Search or scan an item…"
				class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 pl-9 pr-20 text-p-base text-ink-gray-9 placeholder-ink-gray-4 transition-colors focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
			/>

			<div class="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-1">
				<button
					v-if="query"
					class="grid h-7 w-7 place-items-center rounded-md text-ink-gray-5 transition-colors hover:bg-surface-gray-3 hover:text-ink-gray-7"
					aria-label="Clear search"
					@click="clear"
				>
					<LucideX class="h-4 w-4" />
				</button>
				<LucideScanLine
					class="h-4 w-4 transition-colors duration-200"
					:class="flashing ? 'text-ink-green-3' : 'text-ink-gray-4'"
				/>
				<kbd
					class="ml-0.5 hidden rounded border border-outline-gray-2 bg-surface-gray-2 px-1.5 py-0.5 text-p-xs text-ink-gray-5 lg:block"
				>
					F2
				</kbd>
			</div>
		</div>

		<!-- Camera scan. Hidden where the browser cannot do it, and on desktop,
		     where a HID scanner is already faster than holding up a webcam. -->
		<button
			v-if="cameraScan"
			class="grid h-11 min-w-touch place-items-center rounded-lg border border-outline-gray-2 bg-surface-white px-3 text-ink-gray-7 transition-colors hover:bg-surface-gray-2 active:bg-surface-gray-3 md:hidden"
			aria-label="Scan with camera"
			@click="emit('openScanner')"
		>
			<LucideScanLine class="h-[18px] w-[18px]" />
		</button>

		<!-- Below md there is no docked rail, so the shortcuts live behind this.
		     From md up the rail carries them and this would be a duplicate. -->
		<button
			class="relative grid h-11 min-w-touch place-items-center rounded-lg border border-outline-gray-2 bg-surface-white px-3 text-ink-gray-7 transition-colors hover:bg-surface-gray-2 active:bg-surface-gray-3 md:hidden"
			aria-label="Shortcuts"
			@click="emit('openMenu')"
		>
			<LucideMenu class="h-[18px] w-[18px]" />
			<span
				v-if="heldCount"
				class="absolute -right-1 -top-1 grid h-5 min-w-5 place-items-center rounded-full bg-surface-gray-7 px-1 text-p-xs font-semibold text-ink-white"
			>
				{{ heldCount }}
			</span>
		</button>
	</header>
</template>
