/**
 * Scope the Cashiers picker to the till that was chosen.
 *
 * The child table's `user` is a plain Link to User, so the desk offers every
 * account on the site — Guest, the support login, anyone. For a field that
 * decides who may settle money against this drawer that is the wrong list, and
 * worse than merely untidy: `_set_roster` on the server refuses anybody the POS
 * Profile does not permit, so an unfiltered picker suggests answers that are
 * then rejected on save.
 *
 * Registered for both POS entries because the roster is carried onto the closing
 * entry, and a filter that applied to only one of them would be a filter a
 * reader could not rely on.
 */
const CASHIER_QUERY = 'cosmestics.api.shift.cashier_query'

function scopeCashiersToTill(doctype) {
	frappe.ui.form.on(doctype, {
		setup(frm) {
			// Read `pos_profile` inside the callback, not around it: the query is
			// registered once at setup and the till is usually picked afterwards, so
			// capturing the value here would pin the filter to whatever was set on a
			// blank form — which is nothing.
			frm.set_query('user', 'cosmestics_cashiers', () => ({
				query: CASHIER_QUERY,
				filters: { pos_profile: frm.doc.pos_profile || null },
			}))
		},

		pos_profile(frm) {
			// Rows chosen for the previous till may not be permitted on this one, and
			// the server would reject the lot on save with a message naming only the
			// first. Clearing is the honest response to "this is a different counter".
			if (!frm.doc.cosmestics_cashiers?.length) return
			frm.clear_table('cosmestics_cashiers')
			frm.refresh_field('cosmestics_cashiers')
			frappe.show_alert({
				message: __('Cashiers cleared — this till may allow different staff'),
				indicator: 'orange',
			})
		},
	})
}

scopeCashiersToTill('POS Opening Entry')
scopeCashiersToTill('POS Closing Entry')
