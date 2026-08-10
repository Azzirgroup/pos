import { fmtMoney } from './format'

/**
 * The WhatsApp summary a shop posts to its own group when a sale goes out.
 *
 * One formatter rather than a string built at each call site, because the point
 * of the message is that the group can be read down a day's worth of them and
 * reconciled. Two screens composing "roughly this" in different orders defeats
 * that before the first day is out — the fields have to land in the same place
 * every time or the eye cannot scan them.
 *
 * Every line is dropped when its value is missing rather than printed empty. A
 * walk-in has no name and an off-till sale has no shift, and "Shift: —" is a
 * blank somebody has to interpret; a line that is not there is not read.
 */
export function saleMessage(sale, { shift = null, heading = null } = {}) {
	if (!sale) return ''

	const lines = [heading || `*${sale.is_return ? 'Return' : 'Sale'} · ${sale.name}*`]

	const add = (label, value) => {
		if (value === null || value === undefined || value === '') return
		lines.push(`${label}: ${value}`)
	}

	add('Date', sale.posting_date)
	add('Customer', sale.customer)
	add('Amount', fmtMoney(sale.grand_total))

	// Named separately from the amount: a sale of 700 that is entirely owed and
	// one that is paid are the same number and opposite facts.
	if (Number(sale.outstanding_amount) > 0) {
		add('Owed', fmtMoney(sale.outstanding_amount))
	}

	add('Payment', sale.payment_summary || (sale.payment_modes || []).join(', '))
	add('Till', sale.pos_profile)
	add('Shift', shift)
	add('Served by', sale.owner_name || sale.owner)

	if (sale.is_return && sale.return_against) {
		add('Return of', sale.return_against)
	}

	return lines.join('\n')
}
