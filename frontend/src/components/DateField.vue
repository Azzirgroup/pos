<script setup>
import { computed, ref } from 'vue'
import LucideCalendarDays from '~icons/lucide/calendar-days'

/**
 * A date that reads as a date and opens a calendar when you touch it.
 *
 * A bare `<input type="date">` shows `2026-08-22` and hides its calendar behind
 * a small glyph at one end of the box. On a counter tablet that glyph is a
 * quarter of a fingertip wide, and the rest of the control does nothing when
 * tapped — which is why the modals were reported as having dates that could not
 * be changed. The date was always editable; the way in was too small to find.
 *
 * So the whole control is the target. The label is the day in words — Today,
 * Yesterday, or "Sat, 22 Aug" — and a transparent native input is stretched
 * across it, which is what actually opens the picker.
 *
 * **Transparent, not hidden.** An input with `display: none` has no
 * `showPicker` to call on any browser and no click target of its own, so
 * covering the label with a real (invisible) input is the only version of this
 * that works everywhere. `showPicker()` is called as well where it exists,
 * because Firefox opens on click but Chrome on Android does not always.
 */
const props = defineProps({
	modelValue: { type: String, default: '' },
	label: { type: String, default: '' },
	/** Latest date selectable — a purchase cannot be received tomorrow. */
	max: { type: String, default: '' },
	min: { type: String, default: '' },
	disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

const input = ref(null)

function today() {
	const d = new Date()
	const shifted = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
	return shifted.toISOString().slice(0, 10)
}

function shift(iso, delta) {
	const d = new Date(`${iso}T12:00:00`)
	d.setDate(d.getDate() + delta)
	const s = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
	return s.toISOString().slice(0, 10)
}

/** The day in the words somebody would actually say it in. */
const spoken = computed(() => {
	const value = props.modelValue
	if (!value) return 'Pick a date'
	const now = today()
	if (value === now) return 'Today'
	if (value === shift(now, -1)) return 'Yesterday'
	if (value === shift(now, 1)) return 'Tomorrow'
	return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {
		weekday: 'short',
		day: 'numeric',
		month: 'short',
		year: 'numeric',
	})
})

function open() {
	if (props.disabled) return
	// Chrome on Android will not open the picker from a click on the input
	// alone; Firefox will, and calling this there is harmless.
	try {
		input.value?.showPicker?.()
	} catch {
		// Some browsers throw when `showPicker` is called without a direct user
		// gesture they recognise. The native click behind it still works, so
		// this is genuinely nothing to report.
	}
}
</script>

<template>
	<div class="flex flex-col">
		<label v-if="label" class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
			{{ label }}
		</label>
		<div
			class="relative flex h-11 items-center gap-2 rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 transition-colors focus-within:border-outline-gray-4 focus-within:bg-surface-white"
			:class="disabled ? 'opacity-60' : 'cursor-pointer hover:bg-surface-gray-3'"
			@click="open"
		>
			<LucideCalendarDays class="h-4 w-4 shrink-0 text-ink-gray-5" />
			<span class="min-w-0 flex-1 truncate text-p-base text-ink-gray-9">{{ spoken }}</span>
			<!-- The real control, stretched over the whole row so a tap anywhere
			     lands on it. Kept at `opacity-0` rather than hidden — see the note
			     at the top of this file. -->
			<input
				ref="input"
				:value="modelValue"
				type="date"
				:max="max || undefined"
				:min="min || undefined"
				:disabled="disabled"
				:aria-label="label || 'Pick a date'"
				class="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-default"
				@input="emit('update:modelValue', $event.target.value)"
			/>
		</div>
	</div>
</template>
