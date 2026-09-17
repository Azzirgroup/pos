// A stock transfer request waits for the store keeper (`cosmestics_approval`).
// The same two actions the till offers: Approve moves the stock, Reject stops
// the request. The server decides who may — see `cosmestics.api.stock`.
frappe.ui.form.on("Material Request", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || frm.doc.cosmestics_approval !== "Pending") return;

		frm.dashboard.set_headline_alert(
			__("This transfer is waiting for approval. Nothing moves until it is approved."),
			"orange"
		);

		frm.add_custom_button(__("Approve & move stock"), () => {
			frappe.confirm(__("Approve {0} and move the stock now?", [frm.doc.name]), () =>
				frappe
					.call({
						method: "cosmestics.api.stock.approve_transfer",
						args: { name: frm.doc.name },
						freeze: true,
					})
					.then((r) => {
						frappe.show_alert({ message: r.message.message, indicator: "green" });
						frm.reload_doc();
					})
			);
		}, __("Approval"));

		frm.add_custom_button(__("Reject"), () => {
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Why (optional)") },
				(values) =>
					frappe
						.call({
							method: "cosmestics.api.stock.reject_transfer",
							args: { name: frm.doc.name, reason: values.reason },
							freeze: true,
						})
						.then((r) => {
							frappe.show_alert({ message: r.message.message, indicator: "red" });
							frm.reload_doc();
						}),
				__("Reject {0}", [frm.doc.name]),
				__("Reject")
			);
		}, __("Approval"));
	},
});
