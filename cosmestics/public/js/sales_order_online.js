// Online shop orders on the Sales Order form: a banner saying so, with the
// order's status and history. The workflow itself is driven from the staff
// app's Online orders screen (cosmestics/api/online_orders.py).
frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (!frm.doc.cosmestics_online_order) return;
		const status = frm.doc.cosmestics_order_status || "Draft";
		const colours = {
			Draft: "gray",
			"Order Received": "blue",
			Processing: "orange",
			"Out for Delivery": "purple",
			"Ready for Pickup": "purple",
			Complete: "green",
			Cancelled: "red",
		};
		const log = (frm.doc.cosmestics_status_log || [])
			.map((r) => `${frappe.utils.escape_html(r.status)} - ${frappe.datetime.str_to_user(r.changed_at)}`)
			.join(" &nbsp;→&nbsp; ");
		frm.dashboard.set_headline_alert(
			`<div class="d-flex flex-wrap align-items-center" style="gap:8px">
				<span class="indicator-pill ${colours[status] || "gray"}">${__("Online order")}: ${__(status)}</span>
				${frm.doc.cosmestics_mpesa_receipt ? `<span class="text-muted">M-Pesa ${frappe.utils.escape_html(frm.doc.cosmestics_mpesa_receipt)}</span>` : ""}
				${log ? `<span class="text-muted small">${log}</span>` : ""}
			</div>`
		);
		if (["Order Received", "Processing", "Out for Delivery", "Ready for Pickup"].includes(status)) {
			frm.add_custom_button(__("Open in Online orders"), () => {
				window.open("/pos/online-orders", "_blank");
			});
		}
	},
});
