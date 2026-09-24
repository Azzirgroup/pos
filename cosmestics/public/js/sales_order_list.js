// Online shop orders stand out in the Sales Order list: their own status
// (Order Received, Processing, Out for Delivery…) instead of ERPNext's.
(function () {
	const settings = (frappe.listview_settings["Sales Order"] = frappe.listview_settings["Sales Order"] || {});
	const original = settings.get_indicator;
	settings.add_fields = [...(settings.add_fields || []), "cosmestics_online_order", "cosmestics_order_status"];
	const colours = {
		Draft: "gray",
		"Order Received": "blue",
		Processing: "orange",
		"Out for Delivery": "purple",
		"Ready for Pickup": "purple",
		Complete: "green",
		Cancelled: "red",
	};
	settings.get_indicator = function (doc) {
		if (doc.cosmestics_online_order && doc.cosmestics_order_status) {
			const s = doc.cosmestics_order_status;
			return [__("Online · {0}", [__(s)]), colours[s] || "gray", `cosmestics_order_status,=,${s}`];
		}
		return original ? original.call(this, doc) : undefined;
	};
})();
