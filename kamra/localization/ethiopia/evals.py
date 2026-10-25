"""Ethiopia pack checks for the eval harness. Registered through the
`kamra_eval_checks` hook, so the pack adds checks without editing the
harness's own list."""

import frappe

from kamra.scripts.eval_harness import check

PE = "EVAL Addis Hotel"


def _property():
	"""An Ethiopian property made the way the wizard makes one."""
	if not frappe.db.exists("Property", PE):
		from kamra.api import setup_property
		setup_property({
			"property": {"property_name": PE, "city": "Addis Ababa",
			             "country": "Ethiopia"},
			"room_types": [{"code": "STD", "name": "Standard",
			                "base_price": 6500}],
			"rooms": [{"room_type_code": "STD", "numbers": ["101"]}],
		})
	rt = frappe.db.get_value("Room Type", {"property": PE})
	return frappe.get_doc("Property", PE), rt


@check("Ethiopia pack: picked by country, ETB, Addis clock, 15% VAT quote")
def e1():
	from kamra.localization import amount_in_words, pack_for
	from kamra.pricing import quote

	prop, rt = _property()
	pack = pack_for(PE)
	assert pack.__name__.endswith("ethiopia"), pack.__name__
	assert prop.currency == "ETB", prop.currency
	assert prop.timezone == "Africa/Addis_Ababa", prop.timezone
	loc = pack.locale(prop)
	assert loc["currency"] == "ETB" and loc["currency_symbol"] == "Br ", loc
	ctx = pack.invoice_context(prop)
	assert ctx["tax_id_label"] == "TIN" and "Tax Invoice" in ctx["footer"], ctx
	# a room type with no tax % takes the standard 15%
	q = quote(PE, rt, "2030-02-01", "2030-02-02", 2, 0)
	assert q["room_total"] == 6500, q["room_total"]
	assert q["tax_amount"] == 975 and q["amount_after_tax"] == 7475, q
	words = amount_in_words(pack, prop, 7475.5)
	assert "Birr" in words and "Santim" in words, words


@check("Ethiopia ID types: Fayda and Kebele ID, property can replace the list")
def e2():
	from kamra.localization import front_desk_vocabulary, pack_for, validate_id_type

	_property()
	v = front_desk_vocabulary(pack_for(PE), PE)
	assert "Fayda National ID" in v["id_types"] and "Kebele ID" in v["id_types"], v
	assert "Aadhaar" not in v["id_types"], v
	assert "UPI" not in v["payment_modes"], v
	validate_id_type(PE, "Kebele ID")
	try:
		validate_id_type(PE, "Aadhaar")
		raise AssertionError("Aadhaar accepted in Ethiopia")
	except frappe.ValidationError:
		pass
	frappe.db.set_value("Property", PE, "id_types", "Passport\nEmployee Card\n")
	frappe.clear_document_cache("Property", PE)
	v = front_desk_vocabulary(pack_for(PE), PE)
	assert v["id_types"] == ["Passport", "Employee Card"], v
	validate_id_type(PE, "Employee Card")


@check("Ethiopian guest phone: 9/7 mobiles only; foreign and OTA numbers untouched")
def e3():
	from kamra.localization import phone_error

	for ok in ("+251911234567", "+251 722 345 678", "00251911234567",
	           "+2510911234567"):
		assert phone_error(ok) is None, ok
	for bad in ("+251115500100", "+25191123456", "+2519112345678"):
		assert phone_error(bad), bad
	# not +251: no Ethiopian rule applies
	assert phone_error("+447700900123") is None
	assert phone_error("0911234567") is None

	def guest(phone, **flags):
		g = frappe.get_doc({"doctype": "Guest", "first_name": "EVAL ET",
		                    "phone": phone})
		g.flags.update(flags)
		return g.insert(ignore_permissions=True)

	guest("+251911000001")
	try:
		guest("+251115500101")
		raise AssertionError("an Addis landline was accepted as a guest phone")
	except frappe.ValidationError:
		pass
	# an OTA booking is never refused over a number's format
	guest("+251115500102", ignore_phone_rules=True)


# ── Chapa (Phase 2.1). Every Chapa HTTP call is mocked: requests.post for
# initialize and refund, requests.get for verify. ──────────────────────────

WHSEC = "eval-chapa-whsec"


class _Resp:
	def __init__(self, status_code, body):
		self.status_code, self._body = status_code, body

	def json(self):
		return self._body


def _chapa_settings(**extra):
	name = frappe.db.get_value("Payment Gateway Settings", {"property": PE})
	gw = frappe.get_doc("Payment Gateway Settings", name) if name \
		else frappe.new_doc("Payment Gateway Settings")
	gw.update({"property": PE, "gateway": "Chapa", "enabled": 1,
	           "test_mode": 0, "key_id": "CHAPUBK_TEST-eval",
	           "key_secret": "CHASECK_TEST-eval", "webhook_secret": WHSEC,
	           **extra})
	gw.save(ignore_permissions=True)
	return gw


def _folio(name="EVAL Chapa Guest", day=40):
	"""A booking's guest folio. The eval hotel has one room, so each check
	books its own night."""
	from frappe.utils import add_days, nowdate

	from kamra.api import create_booking
	from kamra.folio import open_folio

	_, rt = _property()
	b = create_booking(PE, rt, add_days(nowdate(), day), add_days(nowdate(), day + 1),
	                   name, phone="+251911000101")
	return open_folio(frappe.get_doc("Reservation", b["reservation"])), b["reservation"]


def _link(folio, amount=1500):
	"""A Chapa link with initialize mocked; returns (link, the body sent)."""
	from unittest.mock import patch

	from kamra import payments

	sent = {}

	def post(url, json=None, headers=None, timeout=None, **kw):
		sent.update(url=url, body=json, headers=headers)
		return _Resp(200, {"status": "success", "message": "Hosted Link",
		                   "data": {"checkout_url": "https://checkout.chapa.co/checkout/payment/EVAL"}})

	with patch("requests.post", post):
		link = payments.create_payment_link(folio, amount=amount,
		                                    purpose="Booking deposit")
	return link, sent


def _verified(tx_ref, status="success", amount=1500, currency="ETB",
              reference="APeval1"):
	def get(url, headers=None, timeout=None, **kw):
		assert url.endswith(f"/transaction/verify/{tx_ref}"), url
		return _Resp(200, {"status": "success", "message": "Payment details",
		                   "data": {"tx_ref": tx_ref, "status": status,
		                            "amount": amount, "currency": currency,
		                            "reference": reference}})
	return get


def _event(tx_ref, event="charge.success", amount="1500.00", reference="APeval1"):
	import hashlib
	import hmac
	import json

	body = json.dumps({"event": event, "type": "API", "tx_ref": tx_ref,
	                   "reference": reference, "status": "success",
	                   "amount": amount, "currency": "ETB"}).encode()
	return body, {"x-chapa-signature":
	              hmac.new(WHSEC.encode(), body, hashlib.sha256).hexdigest()}


def _refused(fn, exc=frappe.ValidationError):
	try:
		fn()
	except exc:
		frappe.clear_messages()
		return True
	return False


@check("Chapa: link initialized server-side in ETB, fresh tx_ref per attempt")
def e4():
	from kamra import localization as loc

	_property()
	assert loc.payment_gateways(loc.pack_for(PE)) == ["Chapa"]
	_chapa_settings()
	folio, _ = _folio()
	link, sent = _link(folio)
	assert sent["url"] == "https://api.chapa.co/v1/transaction/initialize", sent["url"]
	assert sent["headers"]["Authorization"] == "Bearer CHASECK_TEST-eval"
	body = sent["body"]
	# the amount is the server's, as a 2-decimal string, in the property's currency
	assert body["amount"] == "1500.00" and body["currency"] == "ETB", body
	assert body["tx_ref"] == link["link_id"], (body, link)
	assert "kamra.payments.gateway_callback?gateway=Chapa" in body["callback_url"], body
	assert body["tx_ref"] in body["return_url"], body
	assert body["phone_number"] == "0911000101", body
	assert link["url"].startswith("https://checkout.chapa.co/"), link
	tx = frappe.get_doc("Payment Gateway Transaction", link["link_id"])
	assert (tx.gateway, tx.folio, tx.status, tx.currency) == \
		("Chapa", folio, "Pending", "ETB"), tx.as_dict()
	assert float(tx.amount) == 1500 and tx.sandbox, tx.as_dict()
	# a second attempt is a new transaction, never a reused reference
	link2, _ = _link(folio)
	assert link2["link_id"] != link["link_id"]
	# Chapa refusing the call surfaces as an error and records nothing
	from unittest.mock import patch

	from kamra import payments
	before = frappe.db.count("Payment Gateway Transaction", {"folio": folio})
	with patch("requests.post", lambda *a, **k: _Resp(400, {"message": "Invalid API Key"})):
		assert _refused(lambda: payments.create_payment_link(folio, amount=100))
	assert frappe.db.count("Payment Gateway Transaction", {"folio": folio}) == before


@check("Chapa webhook: signed and re-verified posts once; forged, tampered and unverified refused")
def e5():
	from unittest.mock import patch

	from kamra import payments

	_property()
	_chapa_settings()
	folio, res = _folio("EVAL Chapa Webhook", 42)
	link, _ = _link(folio)
	tx_ref = link["link_id"]
	body, headers = _event(tx_ref)

	with patch("requests.get", _verified(tx_ref)):
		# no signature, a forged one, and a tampered body are all refused
		assert _refused(lambda: payments.handle_webhook("Chapa", body, {}),
		                frappe.PermissionError)
		assert _refused(lambda: payments.handle_webhook(
			"Chapa", body, {"x-chapa-signature": "forged"}), frappe.PermissionError)
		tampered = body.replace(b'"1500.00"', b'"1.00"')
		assert _refused(lambda: payments.handle_webhook("Chapa", tampered, headers),
		                frappe.PermissionError)
		assert payments.handle_webhook("Chapa", body, headers)["posted"]
		# Chapa retries: the same event never posts twice
		assert not payments.handle_webhook("Chapa", body, headers)["posted"]
	pays = [p for p in frappe.get_doc("Folio", folio).payments if p.reference == tx_ref]
	assert len(pays) == 1 and pays[0].mode == "Payment Link" and \
		pays[0].payment_kind == "Advance" and float(pays[0].amount) == 1500, pays
	tx = frappe.get_doc("Payment Gateway Transaction", tx_ref)
	assert tx.status == "Success" and tx.gateway_reference == "APeval1", tx.as_dict()
	assert float(frappe.db.get_value("Reservation", res, "advance_paid")) == 1500

	# a signed "success" that Chapa's verify API does not confirm posts nothing
	link2, _ = _link(folio)
	body2, headers2 = _event(link2["link_id"], reference="APeval2")
	with patch("requests.get", _verified(link2["link_id"], status="pending")):
		assert not payments.handle_webhook("Chapa", body2, headers2).get("posted")
	assert frappe.db.get_value("Payment Gateway Transaction", link2["link_id"],
	                           "status") == "Pending"
	# a failed charge marks the attempt failed, posts nothing
	body3, headers3 = _event(link2["link_id"], event="charge.failed/cancelled")
	with patch("requests.get", _verified(link2["link_id"], status="failed")):
		assert not payments.handle_webhook("Chapa", body3, headers3).get("posted")
	assert frappe.db.get_value("Payment Gateway Transaction", link2["link_id"],
	                           "status") == "Failed"
	assert sum(1 for p in frappe.get_doc("Folio", folio).payments
	           if p.mode == "Payment Link") == 1


@check("Chapa sweep: a missed webhook still posts; failed and stale links close out")
def e6():
	from unittest.mock import patch

	from frappe.utils import add_to_date, now_datetime

	from kamra import payments

	_property()
	_chapa_settings(link_expiry_hours=24)
	folio, _ = _folio("EVAL Chapa Sweep", 44)
	paid, _ = _link(folio, 700)
	failed, _ = _link(folio, 800)
	stale, _ = _link(folio, 900)
	fresh, _ = _link(folio, 950)
	old = add_to_date(now_datetime(), hours=-30)
	frappe.db.set_value("Payment Gateway Transaction", stale["link_id"],
	                    "creation", old, update_modified=False)
	for name in (paid["link_id"], failed["link_id"], stale["link_id"], fresh["link_id"]):
		frappe.db.set_value("Payment Gateway Transaction", name, "last_checked",
		                    add_to_date(now_datetime(), minutes=-30),
		                    update_modified=False)
	answers = {paid["link_id"]: ("success", 700), failed["link_id"]: ("failed", 800),
	           stale["link_id"]: ("pending", 900), fresh["link_id"]: ("pending", 950)}

	def get(url, headers=None, timeout=None, **kw):
		tx_ref = url.rsplit("/", 1)[-1]
		status, amount = answers[tx_ref]
		return _Resp(200, {"status": "success", "data": {
			"tx_ref": tx_ref, "status": status, "amount": amount,
			"currency": "ETB", "reference": f"AP-{tx_ref[-6:]}"}})

	with patch("requests.get", get):
		payments.sweep_pending_transactions()
	status = {n: frappe.db.get_value("Payment Gateway Transaction", n, "status")
	          for n in answers}
	assert status == {paid["link_id"]: "Success", failed["link_id"]: "Failed",
	                  stale["link_id"]: "Expired", fresh["link_id"]: "Pending"}, status
	pays = [float(p.amount) for p in frappe.get_doc("Folio", folio).payments
	        if p.mode == "Payment Link"]
	assert pays == [700], pays
	# the guest's return page verifies too, and settles idempotently
	assert payments.check_transaction(paid["link_id"])["status"] == "Success"
	# a payment that lands after the link expired is still money received
	answers[stale["link_id"]] = ("success", 900)
	body, headers = _event(stale["link_id"], amount="900.00")
	with patch("requests.get", get):
		assert payments.handle_webhook("Chapa", body, headers)["posted"]
	assert frappe.db.get_value("Payment Gateway Transaction", stale["link_id"],
	                           "status") == "Success"


@check("Chapa refund: by Chapa's own reference, recorded on folio and transaction")
def e7():
	from unittest.mock import patch

	from kamra import payments

	_property()
	_chapa_settings()
	folio, _ = _folio("EVAL Chapa Refund", 46)
	link, _ = _link(folio)
	tx_ref = link["link_id"]
	body, headers = _event(tx_ref, reference="APrefund1")
	with patch("requests.get", _verified(tx_ref, reference="APrefund1")):
		assert payments.handle_webhook("Chapa", body, headers)["posted"]

	calls = []

	def post(url, json=None, data=None, headers=None, timeout=None, **kw):
		calls.append((url, json or data))
		return _Resp(200, {"status": "success", "message": "Refund initiated",
		                   "data": {"reference": "RFeval1"}})

	with patch("requests.post", post):
		out = payments.refund_gateway_payment(folio, tx_ref, 500, "Guest shortened stay")
	assert calls[0][0] == "https://api.chapa.co/v1/refund/APrefund1", calls
	assert calls[0][1]["amount"] == "500.00", calls
	assert out["ok"], out
	tx = frappe.get_doc("Payment Gateway Transaction", tx_ref)
	assert tx.status == "Partly Refunded" and float(tx.refunded_amount) == 500, tx.as_dict()
	refunds = [p for p in frappe.get_doc("Folio", folio).payments
	           if p.payment_kind == "Refund"]
	assert len(refunds) == 1 and float(refunds[0].amount) == -500 and \
		refunds[0].mode == "Payment Link", refunds
	# more than what is left on the transaction is refused before calling Chapa
	with patch("requests.post", post):
		assert _refused(lambda: payments.refund_gateway_payment(folio, tx_ref, 1001, "x"))
	assert len(calls) == 1
	# Chapa refusing the refund posts nothing
	with patch("requests.post", lambda *a, **k: _Resp(400, {"message": "Insufficient balance"})):
		assert _refused(lambda: payments.refund_gateway_payment(folio, tx_ref, 100, "x"))
	assert sum(1 for p in frappe.get_doc("Folio", folio).payments
	           if p.payment_kind == "Refund") == 1
	# the rest refunds in full
	with patch("requests.post", post):
		payments.refund_gateway_payment(folio, tx_ref, 1000, "Cancelled")
	assert frappe.db.get_value("Payment Gateway Transaction", tx_ref, "status") == "Refunded"


def run():
	for fn in (e1, e2, e3, e4, e5, e6, e7):
		fn()
