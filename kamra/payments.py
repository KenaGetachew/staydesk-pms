"""Payment Links for folio settlement.

Lightweight by design: one REST call out, one webhook in. Which gateways a
property may use is its country pack's call (India: Razorpay, Cashfree;
Ethiopia: Chapa); this module decides what a link is for and posts the
money, and never speaks a gateway's API itself.

Every link is one Payment Gateway Transaction (pending, success, failed,
expired, partly refunded, refunded). Where the provider can be asked what
happened to a link (check_status), a missed webhook is recovered by the
pending sweep and by the guest's return page, so no payment is lost.
"""

from decimal import Decimal

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime, nowdate

from kamra.authz import require_roles


def _settings(property: str):
	name = frappe.db.get_value(
		"Payment Gateway Settings", {"property": property, "enabled": 1})
	if not name:
		frappe.throw(
			"No payment gateway configured for this property. "
			"Add API keys under Payment Gateway Settings."
		)
	return frappe.get_doc("Payment Gateway Settings", name)


def create_payment_link(folio_name: str, amount: float | None = None,
                        purpose: str = "Stay bill") -> dict:
	"""A link for the folio's balance - or, before arrival, for an explicit
	amount (a booking deposit), when the folio has no charges yet."""
	from kamra import localization as loc

	folio = frappe.get_doc("Folio", folio_name)
	if folio.status == "Closed":
		frappe.throw("Folio is closed.")
	amount = float(amount) if amount else float(folio.balance or 0)
	if amount <= 0:
		frappe.throw("Nothing due on this folio.")
	pack = loc.pack_for(folio.property)
	if not loc.payment_gateways(pack):
		frappe.throw("Online payment links are not available for this property's country.")
	settings = _settings(folio.property)
	guest = frappe.get_doc("Guest", folio.guest)
	currency = frappe.get_cached_value("Property", folio.property,
	                                   "currency") or "INR"

	simulated = bool(settings.test_mode)
	if simulated:
		# local demo: fake link, settle via the webhook simulator
		link_id = f"plink_TEST{frappe.generate_hash(length=10)}"
		url = loc.test_gateway_link(pack, settings.gateway, link_id)
	else:
		link_id, url = loc.create_gateway_link(
			pack, settings,
			amount=amount,
			currency=currency.upper(),
			reference=folio.name,
			description=f"{purpose} {folio.name} · {folio.guest_name}",
			customer={"name": guest.full_name, "contact": guest.phone or "",
			          "email": guest.email or ""},
			notes={"folio": folio.name, "property": folio.property},
		)

	frappe.get_doc({
		"doctype": "Payment Gateway Transaction",
		"tx_ref": link_id,
		"gateway": settings.gateway,
		"property": folio.property,
		"folio": folio.name,
		"purpose": purpose,
		"amount": amount,
		"currency": currency.upper(),
		"simulated": simulated,
		"sandbox": not simulated and loc.gateway_sandbox(pack, settings),
		"checkout_url": url,
		"last_checked": now_datetime(),
	}).insert(ignore_permissions=True)
	folio.db_set("payment_link_id", link_id, update_modified=False)
	folio.db_set("payment_link_url", url, update_modified=False)
	folio.db_set("payment_link_amount", amount, update_modified=False)

	from kamra.savings import log_action
	log_action("send_payment_link", "Folio", folio.name, folio.property,
	           minutes_saved=4,
	           rationale=f"{purpose} link {currency} {amount:,.0f} for {guest.full_name}",
	           channel="API")
	return {"url": url, "link_id": link_id, "amount": amount,
	        "currency": currency, "test_mode": bool(settings.test_mode)}


def settle_payment_link(folio_name: str, link_id: str, amount: float) -> bool:
	"""Post money received through a link, once per link payment. Money that
	arrives before the guest does is an Advance on the booking: it counts
	toward the deposit and confirms a held booking."""
	folio = frappe.get_doc("Folio", folio_name)
	if amount <= 0 or any(p.reference == link_id for p in folio.payments):
		return False
	_mark(link_id, "Success", paid_on=now_datetime())
	res = frappe.get_doc("Reservation", folio.reservation) \
		if folio.reservation else None
	pre_arrival = bool(res and res.status in (
		"Confirmed", "Pending Payment", "Held"))
	folio.append("payments", {
		"posting_date": nowdate(),
		"payment_kind": "Advance" if pre_arrival else "Payment",
		"mode": "Payment Link",
		"amount": amount,
		"reference": link_id,
	})
	from kamra.folio import _recalculate
	_recalculate(folio)
	folio.save(ignore_permissions=True)
	try:
		from kamra.ledger import record_payment_ledger
		record_payment_ledger(folio, folio.payments[-1].as_dict())
	except Exception:
		frappe.log_error(title="ledger payment-link write failed")
	if pre_arrival:
		frappe.db.set_value("Reservation", res.name, "advance_paid",
		                    float(res.advance_paid or 0) + amount)
		if res.status in ("Pending Payment", "Held"):
			from kamra.api import _confirm_status
			_confirm_status(res)
	from kamra.savings import log_action
	log_action("payment_received", "Folio", folio.name, folio.property,
	           minutes_saved=3,
	           rationale=f"{amount:,.0f} {'deposit ' if pre_arrival else ''}"
	                     f"auto-posted from payment link",
	           agent_name="Payments", channel="API")
	return True


def _mark(link_id: str, status: str | None = None, **fields):
	"""Update a link's transaction record, if it has one (links made before
	transactions were recorded have none)."""
	if not frappe.db.exists("Payment Gateway Transaction", link_id):
		return
	if status:
		fields["status"] = status
	fields["last_checked"] = now_datetime()
	frappe.db.set_value("Payment Gateway Transaction", link_id, fields,
	                    update_modified=False)


def _apply_result(folio_name: str, result: dict) -> dict:
	"""Act on what a gateway says about a link: {link_id, status, amount,
	currency, reference}. Only "success" posts money, and only once."""
	link_id = result["link_id"]
	status = result.get("status") or "success"
	tx = frappe.db.get_value("Payment Gateway Transaction", link_id,
	                         ["status", "currency"], as_dict=True)
	if status == "success":
		currency = (result.get("currency") or "").upper()
		if tx and currency and tx.currency and currency != tx.currency:
			# never post USD as if it were Birr; a person sorts it out
			_mark(link_id, status_detail=f"Paid in {currency}, expected "
			                             f"{tx.currency} - not posted")
			frappe.log_error(title=f"gateway payment in wrong currency: {link_id}")
			return {"ok": False, "folio": folio_name, "posted": False,
			        "status": "currency mismatch"}
		if result.get("reference"):
			_mark(link_id, gateway_reference=result["reference"])
		posted = settle_payment_link(folio_name, link_id, float(result["amount"]))
		if not posted:
			_mark(link_id)  # retried event: already posted, just touch it
		return {"ok": True, "folio": folio_name, "posted": posted, "status": "success"}
	if status == "failed":
		if tx and tx.status in ("Pending", "Expired"):
			_mark(link_id, "Failed")
	elif status == "pending":
		_mark(link_id)
	else:
		# refunded or reversed on the gateway's side, outside Kamra: the
		# folio is not touched; a person decides what it means
		_mark(link_id, status_detail=result.get("detail") or status)
		frappe.log_error(title=f"gateway reported {status}: {link_id}",
		                 message=frappe.as_json(result))
	return {"ok": True, "folio": folio_name, "posted": False, "status": status}


def handle_webhook(gateway: str, payload: bytes, headers: dict) -> dict:
	"""Settle a gateway's "link paid" event. Idempotent: a retried event
	never posts the same payment twice. A bad signature raises."""
	from kamra import localization as loc

	paid = loc.parse_payment_webhook(gateway, payload, headers, _settings)
	if not paid:
		return {"ignored": True}
	return _apply_result(paid["folio"], paid)


def check_transaction(link_id: str, min_interval: int = 0) -> dict:
	"""Ask the gateway what happened to one link and act on it - from the
	pending sweep, the guest's return page and the gateway's callback.
	Expires a link left unpaid past the property's expiry. Returns what
	the return page shows."""
	from kamra import localization as loc

	tx = frappe.get_doc("Payment Gateway Transaction", link_id)
	recent = tx.last_checked and min_interval and \
		get_datetime(tx.last_checked) > add_to_date(now_datetime(), seconds=-min_interval)
	if tx.status == "Pending" and not tx.simulated and not recent:
		pack = loc.pack_for(tx.property)
		settings = _settings(tx.property)
		if settings.gateway == tx.gateway and \
		   loc.gateway_can(pack, tx.gateway, "check_status"):
			result = loc.check_gateway_status(pack, settings, link_id)
			_apply_result(tx.folio, {"link_id": link_id, **result})
			tx.reload()
		hours = int(settings.get("link_expiry_hours") or 24)
		if tx.status == "Pending" and \
		   get_datetime(tx.creation) < add_to_date(now_datetime(), hours=-hours):
			_mark(link_id, "Expired")
			tx.reload()
	return {"status": tx.status, "amount": float(tx.amount or 0),
	        "currency": tx.currency, "property": tx.property,
	        "purpose": tx.purpose}


def sweep_pending_transactions(limit: int = 200):
	"""Scheduled: re-check pending links not looked at for 5 minutes, so a
	webhook that never arrived still posts the payment."""
	cutoff = add_to_date(now_datetime(), minutes=-5)
	names = frappe.get_all(
		"Payment Gateway Transaction",
		filters={"status": "Pending", "simulated": 0},
		or_filters=[["last_checked", "is", "not set"],
		            ["last_checked", "<", cutoff]],
		pluck="name", order_by="last_checked asc", limit=limit)
	for name in names:
		try:
			check_transaction(name)
		except Exception:
			frappe.log_error(title=f"payment sweep failed: {name}")
			_mark(name)  # don't retry a broken one every run


def _request_headers() -> dict:
	return {k.lower(): v for k, v in (frappe.request.headers or {}).items()}


def _webhook(gateway: str) -> dict:
	out = handle_webhook(gateway, frappe.request.get_data() or b"{}",
	                     _request_headers())
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- persists the completed operation before returning to an external/public caller; reviewed as intentional
	return out


def _gateway_arg() -> str:
	from kamra import localization as loc

	gateway = (frappe.request.args.get("gateway") or "").strip()
	if not gateway or not loc._gateway_provider_any(gateway):
		frappe.throw("Unknown payment gateway.", frappe.PermissionError)
	return gateway


@frappe.whitelist(allow_guest=True, methods=["POST"])
def gateway_webhook():
	"""Signed payment events for any pack's gateway:
	/api/method/kamra.payments.gateway_webhook?gateway=Chapa"""
	return _webhook(_gateway_arg())


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def gateway_callback():
	"""The unsigned "checkout finished" ping some gateways send (Chapa's
	callback_url). It carries no trust: it only makes us verify the link
	with the gateway, at most every 30 seconds."""
	gateway = _gateway_arg()
	link_id = frappe.form_dict.get("trx_ref") or frappe.form_dict.get("tx_ref")
	if not link_id or frappe.db.get_value(
			"Payment Gateway Transaction", link_id, "gateway") != gateway:
		return {"ignored": True}
	out = check_transaction(link_id, min_interval=30)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- persists the completed operation before returning to an external/public caller; reviewed as intentional
	return {"ok": True, "status": out["status"]}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def razorpay_webhook():
	"""Razorpay calls this on payment_link.paid. Point the webhook at
	/api/method/kamra.payments.razorpay_webhook"""
	return _webhook("Razorpay")


@frappe.whitelist(allow_guest=True, methods=["POST"])
def cashfree_webhook():
	"""Cashfree posts here for every link (set per link as notify_url)."""
	return _webhook("Cashfree")


@frappe.whitelist()
def gateway_transactions(folio: str) -> list[dict]:
	"""Every online payment attempt on a folio, newest first, for the
	folio's payments panel."""
	from kamra.crs import assert_property_access

	property = frappe.db.get_value("Folio", folio, "property")
	if not property:
		frappe.throw("Folio not found.", frappe.DoesNotExistError)
	assert_property_access(property)
	return frappe.get_all(
		"Payment Gateway Transaction", filters={"folio": folio},
		fields=["name", "gateway", "purpose", "status", "amount", "currency",
		        "refunded_amount", "gateway_reference", "simulated", "sandbox",
		        "checkout_url", "paid_on", "creation", "status_detail"],
		order_by="creation desc", ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
@require_roles("Finance", "Hotel Admin")
def refund_gateway_payment(folio: str, link_id: str, amount: float,
                           reason: str, pin: str | None = None) -> dict:
	"""Give money back through the gateway it came in on - all of it or
	part. The folio refund row and the gateway refund happen together: if
	the gateway refuses, nothing is posted."""
	from kamra import localization as loc
	from kamra.api import _refund_folio_payment

	tx = frappe.get_doc("Payment Gateway Transaction", link_id)
	if tx.folio != folio:
		frappe.throw("That payment is not on this folio.")
	if tx.status not in ("Success", "Partly Refunded"):
		frappe.throw(f"Only a successful payment can be refunded (this one is {tx.status}).")
	amount = Decimal(str(amount or 0)).quantize(Decimal("0.01"))
	left = Decimal(str(tx.amount or 0)) - Decimal(str(tx.refunded_amount or 0))
	if amount <= 0:
		frappe.throw("Refund amount must be positive.")
	if amount > left:
		frappe.throw(f"Only {tx.currency} {left:,.2f} of this payment is left to refund.")
	if not (reason or "").strip():
		frappe.throw("A refund reason is required.")
	pack = loc.pack_for(tx.property)
	settings = _settings(tx.property)
	if not tx.simulated and settings.gateway != tx.gateway:
		frappe.throw(f"This property no longer takes payments through {tx.gateway}.")

	sp = "gateway_refund"
	frappe.db.savepoint(sp)
	try:
		_refund_folio_payment(folio, float(amount), "Payment Link",
		                      f"{tx.gateway} refund of {link_id}: {reason}",
		                      pin=pin)
		ref = f"{link_id}-SIM" if tx.simulated else \
			loc.refund_gateway_payment(pack, settings, tx, amount, reason.strip())
	except Exception:
		frappe.db.rollback(save_point=sp)
		raise
	refunded = Decimal(str(tx.refunded_amount or 0)) + amount
	_mark(link_id, "Refunded" if refunded >= Decimal(str(tx.amount)) else "Partly Refunded",
	      refunded_amount=float(refunded),
	      refund_references="\n".join(filter(None, [tx.refund_references, ref])))
	return {"ok": True, "refund_reference": ref, "refunded": float(refunded),
	        "balance": frappe.db.get_value("Folio", folio, "balance")}


@frappe.whitelist()
@require_roles("Hotel Admin", "Finance")
def gateway_info(property: str, gateway: str = "") -> dict:
	"""What the Payments settings card shows beside the keys: where the
	gateway reports payments, and where to open an account."""
	from kamra import localization as loc

	pack = loc.pack_for(property)
	if not gateway:
		gateway = frappe.db.get_value("Payment Gateway Settings",
		                              {"property": property}, "gateway") \
			or (loc.payment_gateways(pack) or [""])[0]
	return loc.gateway_info(pack, gateway)
