<script setup>
import { computed } from 'vue'

/**
 * The payment brand, as a badge.
 *
 * Drawn as inline SVG rather than shipped as image files. Two reasons: a logo
 * fetched from a search result has a licence nobody has checked and a version
 * nobody can vouch for, and a raster badge at 44px goes soft on the high-density
 * screens most tills are. These are vector, tiny, and part of the bundle.
 *
 * Marks are reproduced to identify the payment method being used, which is what
 * a payment badge is for — the same reason they appear on a shop door. Colours
 * follow each brand's own; the wordmark is set in the system sans rather than
 * the brand's licensed typeface.
 *
 * Matching is on the Mode of Payment's *name*, because that is the only thing
 * this app knows about a tender a shop invented. Anything unrecognised falls
 * back to a neutral badge rather than guessing — a wrong logo on a till is worse
 * than none.
 */
const props = defineProps({
	/** Mode of Payment name, or the tender label. */
	name: { type: String, default: '' },
	/** Tender kind from the server, used only as a fallback. */
	kind: { type: String, default: '' },
})

const BRANDS = [
	{ id: 'mpesa', match: /m-?pesa/i },
	{ id: 'airtel', match: /airtel/i },
	{ id: 'visa', match: /visa/i },
	{ id: 'mastercard', match: /master ?card|maestro/i },
	{ id: 'amex', match: /amex|american express/i },
	{ id: 'paypal', match: /paypal/i },
	{ id: 'cash', match: /cash/i },
	{ id: 'card', match: /card|pos machine/i },
	{ id: 'bank', match: /bank|transfer|cheque|check/i },
	{ id: 'credit', match: /credit|account|later/i },
]

const brand = computed(() => {
	const text = `${props.name} ${props.kind}`
	const hit = BRANDS.find((b) => b.match.test(text))
	if (hit) return hit.id
	// The server's kind is coarser than the name but better than nothing.
	if (props.kind === 'cash') return 'cash'
	if (props.kind === 'card') return 'card'
	if (props.kind === 'credit') return 'credit'
	return 'other'
})
</script>

<template>
	<!-- 44×28 keeps every badge the same footprint, so a row of them lines up
	     however wide the wordmarks are. -->
	<svg
		viewBox="0 0 44 28"
		width="44"
		height="28"
		class="shrink-0"
		role="img"
		:aria-label="name || 'Payment method'"
	>
		<!-- M-PESA: white field, Safaricom green wordmark. -->
		<template v-if="brand === 'mpesa'">
			<rect width="44" height="28" rx="4" fill="#fff" stroke="#e2e2e0" />
			<text
				x="22"
				y="18"
				text-anchor="middle"
				font-family="system-ui, sans-serif"
				font-size="8.5"
				font-weight="700"
				fill="#43B02A"
			>
				M-PESA
			</text>
		</template>

		<!-- Airtel: solid red field, white wordmark. -->
		<template v-else-if="brand === 'airtel'">
			<rect width="44" height="28" rx="4" fill="#E40000" />
			<text
				x="22"
				y="18"
				text-anchor="middle"
				font-family="system-ui, sans-serif"
				font-size="8.5"
				font-weight="700"
				fill="#fff"
			>
				airtel
			</text>
		</template>

		<template v-else-if="brand === 'visa'">
			<rect width="44" height="28" rx="4" fill="#fff" stroke="#e2e2e0" />
			<text
				x="22"
				y="19"
				text-anchor="middle"
				font-family="system-ui, sans-serif"
				font-size="10"
				font-weight="700"
				font-style="italic"
				fill="#1A1F71"
			>
				VISA
			</text>
		</template>

		<!-- Mastercard: the interlocking discs, which are the mark itself. -->
		<template v-else-if="brand === 'mastercard'">
			<rect width="44" height="28" rx="4" fill="#fff" stroke="#e2e2e0" />
			<circle cx="18" cy="14" r="7.5" fill="#EB001B" />
			<circle cx="26" cy="14" r="7.5" fill="#F79E1B" fill-opacity="0.85" />
		</template>

		<template v-else-if="brand === 'amex'">
			<rect width="44" height="28" rx="4" fill="#006FCF" />
			<text
				x="22"
				y="18"
				text-anchor="middle"
				font-family="system-ui, sans-serif"
				font-size="9"
				font-weight="700"
				fill="#fff"
			>
				AMEX
			</text>
		</template>

		<template v-else-if="brand === 'paypal'">
			<rect width="44" height="28" rx="4" fill="#fff" stroke="#e2e2e0" />
			<text
				x="22"
				y="18"
				text-anchor="middle"
				font-family="system-ui, sans-serif"
				font-size="8"
				font-weight="700"
				font-style="italic"
				fill="#003087"
			>
				PayPal
			</text>
		</template>

		<!-- Cash has no brand, so it gets a note rather than a wordmark. -->
		<template v-else-if="brand === 'cash'">
			<rect width="44" height="28" rx="4" fill="#EBF7EE" stroke="#B9E3C6" />
			<rect x="9" y="9" width="26" height="11" rx="2" fill="#fff" stroke="#43B02A" />
			<circle cx="22" cy="14.5" r="3" fill="#43B02A" />
		</template>

		<!-- A card machine, for a shop with no named network. -->
		<template v-else-if="brand === 'card'">
			<rect width="44" height="28" rx="4" fill="#0B63CE" />
			<rect x="8" y="10" width="28" height="4" rx="1" fill="#fff" fill-opacity="0.9" />
			<rect x="8" y="17" width="12" height="3" rx="1" fill="#fff" fill-opacity="0.6" />
		</template>

		<template v-else-if="brand === 'bank'">
			<rect width="44" height="28" rx="4" fill="#fff" stroke="#e2e2e0" />
			<path d="M22 7 L33 13 H11 Z" fill="#0B63CE" />
			<rect x="13" y="14" width="3" height="6" fill="#0B63CE" />
			<rect x="20.5" y="14" width="3" height="6" fill="#0B63CE" />
			<rect x="28" y="14" width="3" height="6" fill="#0B63CE" />
			<rect x="11" y="21" width="22" height="2.5" rx="1" fill="#0B63CE" />
		</template>

		<!-- Credit is the absence of a payment, so it is a ledger, not a brand. -->
		<template v-else-if="brand === 'credit'">
			<rect width="44" height="28" rx="4" fill="#FEF6E7" stroke="#F3D9A4" />
			<rect x="13" y="8" width="18" height="12" rx="1.5" fill="#fff" stroke="#C58A0B" />
			<rect x="16" y="11" width="12" height="1.5" fill="#C58A0B" />
			<rect x="16" y="14.5" width="8" height="1.5" fill="#C58A0B" />
		</template>

		<template v-else>
			<rect width="44" height="28" rx="4" fill="#f4f4f3" stroke="#e2e2e0" />
			<text
				x="22"
				y="18"
				text-anchor="middle"
				font-family="system-ui, sans-serif"
				font-size="7.5"
				font-weight="600"
				fill="#7c7c78"
			>
				PAY
			</text>
		</template>
	</svg>
</template>
