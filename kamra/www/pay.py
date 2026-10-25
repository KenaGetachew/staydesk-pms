import frappe

# The guest lands here from the gateway's hosted checkout. Always fresh.
no_cache = 1

MESSAGES = {
	"Success": ("Payment received", "Thank you - your payment is confirmed. "
	            "You can close this page."),
	"Pending": ("Payment being confirmed", "We are waiting for the payment "
	            "provider to confirm. This page updates on refresh; you will "
	            "not be charged twice."),
	"Failed": ("Payment not completed", "The payment did not go through and "
	           "nothing was charged. Ask the hotel for a new payment link."),
	"Expired": ("Link expired", "This payment link has expired. Ask the hotel "
	            "for a new one."),
}


def get_context(context):
	"""Verify the payment with the gateway (a missed webhook is caught
	here too) and tell the guest where it stands. The tx_ref is random
	and unguessable; the page shows only status, amount and hotel name."""
	from kamra.payments import check_transaction

	context.no_breadcrumbs = True
	tx_ref = (frappe.form_dict.get("tx_ref") or frappe.form_dict.get("trx_ref")
	          or "").strip()
	status = "Unknown"
	out = {}
	if tx_ref and frappe.db.exists("Payment Gateway Transaction", tx_ref):
		try:
			out = check_transaction(tx_ref, min_interval=10)
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- a GET from the guest's browser may post the verified payment; persist it
			status = out["status"]
		except Exception:
			frappe.log_error(title=f"payment return page failed: {tx_ref}")
			status = "Pending"
	if status in ("Partly Refunded", "Refunded"):
		status = "Success"
	title, text = MESSAGES.get(status, ("Payment not found",
	                                    "We could not find this payment. "
	                                    "Please contact the hotel."))
	context.status = status
	context.heading = title
	context.text = text
	context.hotel = frappe.db.get_value("Property", out.get("property"),
	                                    "property_name") if out.get("property") else ""
	context.amount = f"{out.get('currency') or ''} {out.get('amount', 0):,.2f}" \
		if out else ""
	context.title = title
