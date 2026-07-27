/**
 * Currency comes from the POS profile once the backend lands; until then the
 * shop default is used. Formatters are built once — creating an Intl formatter
 * per cart line is measurably slow when the cart re-renders on every keystroke.
 */
export const CURRENCY = 'KES'

const money = new Intl.NumberFormat('en-KE', {
	style: 'currency',
	currency: CURRENCY,
	minimumFractionDigits: 2,
	maximumFractionDigits: 2,
})

const moneyCompact = new Intl.NumberFormat('en-KE', {
	minimumFractionDigits: 0,
	maximumFractionDigits: 0,
})

const decimal = new Intl.NumberFormat('en-KE', {
	minimumFractionDigits: 0,
	maximumFractionDigits: 3,
})

/** "KES 1,250.00" — for totals and receipts. */
export function fmtMoney(value) {
	return money.format(Number(value) || 0)
}

/** "1,250" — for dense grids where the currency is already implied. */
export function fmtMoneyShort(value) {
	return moneyCompact.format(Math.round(Number(value) || 0))
}

/** Quantities: whole numbers stay clean, fractional (grams, ml) keep precision. */
export function fmtQty(value) {
	return decimal.format(Number(value) || 0)
}

/** Round to 2dp without float drift (0.1 + 0.2 problems compound over a cart). */
export function round2(value) {
	return Math.round((Number(value) + Number.EPSILON) * 100) / 100
}
