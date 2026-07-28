<script setup>
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'
import { useCameraScanner } from '@/composables/useCameraScanner'
import LucideX from '~icons/lucide/x'
import LucideZap from '~icons/lucide/zap'
import LucideScanLine from '~icons/lucide/scan-line'

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	/** Feedback line — set by the parent when a scan hits or misses. */
	lastResult: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'scan'])

const videoEl = ref(null)
const scanner = useCameraScanner((code) => emit('scan', code))
const { active, error, torchOn, torchAvailable, engine } = scanner

const MESSAGES = {
	unsupported: {
		title: 'Camera scanning could not start',
		body: 'The barcode decoder failed to load. Check the connection and try again, or use a USB/Bluetooth scanner, which works everywhere.',
	},
	insecure: {
		title: 'Needs a secure connection',
		body: 'Browsers only allow camera access over HTTPS. Open the till on its https:// address.',
	},
	denied: {
		title: 'Camera permission denied',
		body: 'Allow camera access for this site in your browser settings, then try again.',
	},
	nocamera: {
		title: 'No camera found',
		body: 'This device has no usable camera. A USB or Bluetooth scanner will still work.',
	},
}

watch(
	() => props.modelValue,
	async (open) => {
		if (open) {
			await nextTick()
			scanner.start(videoEl.value)
		} else {
			scanner.stop()
		}
	},
)

// Leaving the view without releasing the camera keeps the phone's camera light on.
onBeforeUnmount(() => scanner.stop())

function close() {
	emit('update:modelValue', false)
}
</script>

<template>
	<Teleport to="body">
		<Transition
			enter-active-class="transition-opacity duration-150"
			leave-active-class="transition-opacity duration-150"
			enter-from-class="opacity-0"
			leave-to-class="opacity-0"
		>
			<div v-if="modelValue" class="fixed inset-0 z-50 bg-black">
				<!-- Camera feed -->
				<video
					ref="videoEl"
					class="h-full w-full object-cover"
					playsinline
					muted
					autoplay
				/>

				<!-- Viewfinder: a wide, short window matches the shape of a barcode
				     and tells the cashier how to hold the phone without instructions. -->
				<div v-if="active" class="pointer-events-none absolute inset-0 grid place-items-center">
					<div class="relative h-32 w-[78%] max-w-sm">
						<div class="absolute inset-0 rounded-xl border-2 border-white/70" />
						<div
							class="absolute inset-x-0 top-1/2 h-0.5 -translate-y-1/2 bg-red-500/80 shadow-[0_0_8px_rgba(239,68,68,0.9)]"
						/>
					</div>
					<p class="mt-5 px-8 text-center text-p-sm text-white/80">
						Point at the barcode
					</p>
					<!-- The wasm decoder is noticeably slower, so say so rather than
					     let it read as a broken camera. -->
					<p v-if="engine === 'wasm'" class="mt-1 px-8 text-center text-p-xs text-white/50">
						Hold steady — this device uses the slower decoder
					</p>
				</div>

				<!-- Error state -->
				<div
					v-if="error"
					class="absolute inset-0 grid place-items-center bg-surface-white px-6 text-center"
				>
					<div class="max-w-sm">
						<div class="mx-auto grid h-12 w-12 place-items-center rounded-xl bg-surface-gray-3">
							<LucideScanLine class="h-6 w-6 text-ink-gray-6" />
						</div>
						<h2 class="mt-4 text-p-lg font-semibold text-ink-gray-9">
							{{ MESSAGES[error]?.title }}
						</h2>
						<p class="mt-1.5 text-p-base text-ink-gray-6">
							{{ MESSAGES[error]?.body }}
						</p>
						<button
							class="mt-5 min-h-touch w-full rounded-xl bg-surface-gray-7 py-3 text-p-base font-semibold text-ink-white"
							@click="close"
						>
							Back to till
						</button>
					</div>
				</div>

				<!-- Last scan feedback, so a miss is visible without leaving the camera -->
				<Transition
					enter-active-class="transition-all duration-200"
					leave-active-class="transition-all duration-200"
					enter-from-class="opacity-0 translate-y-2"
					leave-to-class="opacity-0"
				>
					<div
						v-if="lastResult && active"
						class="absolute inset-x-4 bottom-24 rounded-xl px-4 py-3 text-center text-p-base font-medium shadow-lg"
						:class="
							lastResult.ok
								? 'bg-surface-green-3 text-ink-white'
								: 'bg-surface-amber-3 text-ink-white'
						"
					>
						{{ lastResult.message }}
					</div>
				</Transition>

				<!-- Controls -->
				<div v-if="active" class="absolute inset-x-0 bottom-0 flex items-center justify-between p-5">
					<button
						class="grid h-12 w-12 place-items-center rounded-full bg-white/15 text-white backdrop-blur transition-colors active:bg-white/25"
						aria-label="Close scanner"
						@click="close"
					>
						<LucideX class="h-5 w-5" />
					</button>

					<!-- Torch matters: shop lighting is often poor at the counter. -->
					<button
						v-if="torchAvailable"
						class="grid h-12 w-12 place-items-center rounded-full backdrop-blur transition-colors"
						:class="torchOn ? 'bg-white text-black' : 'bg-white/15 text-white active:bg-white/25'"
						aria-label="Toggle torch"
						@click="scanner.toggleTorch()"
					>
						<LucideZap class="h-5 w-5" />
					</button>
				</div>

				<button
					v-if="!active && !error"
					class="absolute right-5 top-5 grid h-12 w-12 place-items-center rounded-full bg-white/15 text-white backdrop-blur"
					aria-label="Close scanner"
					@click="close"
				>
					<LucideX class="h-5 w-5" />
				</button>
			</div>
		</Transition>
	</Teleport>
</template>
