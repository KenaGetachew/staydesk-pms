"""Chapa hosted checkout, on the property's own Chapa account.

Chapa aggregates telebirr, CBE Birr, M-Pesa, cards and bank payments, so
one integration covers most of the Ethiopian market. API docs:
https://developer.chapa.co

Calls out: initialize (create a checkout for one tx_ref), verify (what
Chapa says happened to a tx_ref) and refund. Calls in: the signed webhook
(kamra.payments.gateway_webhook?gateway=Chapa) and the unsigned callback
Chapa fires when a checkout finishes (kamra.payments.gateway_callback).
Neither inbound call is trusted for the amount: both end in a verify call,
and only Chapa's verified answer posts money. kamra.payments decides what
a link is for and posts it; this module only speaks Chapa.
"""

import hashlib
import hmac
import json
import re
from decimal import Decimal

import frappe
from frappe.utils import get_url

GATEWAY = "Chapa"
API = "https://api.chapa.co/v1"
SIGNUP_URL = "https://dashboard.chapa.co/register"
# test secret keys look like CHASECK_TEST-xxxx, live ones CHASECK-xxxx
TEST_KEY_PREFIX = "CHASECK_TEST"


def _secret(settings) -> str:
	secret = settings.get_password("key_secret", raise_exception=False)
	if not secret:
		frappe.throw("The Chapa secret key is required for payment links.")
	return secret


def _auth(settings) -> dict:
	return {"Authorization": f"Bearer {_secret(settings)}"}


def _money(v) -> str:
	"""Chapa takes the amount as a decimal string."""
	return str(Decimal(str(v)).quantize(Decimal("0.01")))


def _local_phone(phone: str | None) -> str | None:
	"""Chapa wants 09xxxxxxxx / 07xxxxxxxx. Anything else is left out -
	the guest types a number on the checkout page instead."""
	digits = re.sub(r"\D", "", phone or "")
	if digits.startswith("00"):
		digits = digits[2:]
	if digits.startswith("251"):
		digits = digits[3:]
	digits = digits.lstrip("0")
	if len(digits) == 9 and digits[0] in "97":
		return "0" + digits
	return None


def _plain(text: str, limit: int) -> str:
	# Chapa rejects customization text with anything beyond letters,
	# digits, spaces, dots, hyphens and underscores
	return re.sub(r"[^A-Za-z0-9 ._-]", "", text or "").strip()[:limit]


def _error(resp) -> str:
	try:
		msg = resp.json().get("message")
	except ValueError:
		msg = None
	if isinstance(msg, dict):  # field errors: {"amount": ["..."]}
		msg = "; ".join(f"{k}: {', '.join(v) if isinstance(v, list) else v}"
		                for k, v in msg.items())
	return msg or str(resp.status_code)


def is_sandbox(settings) -> bool:
	return (settings.get_password("key_secret", raise_exception=False)
	        or "").startswith(TEST_KEY_PREFIX)


def create_link(settings, *, amount: float, currency: str, reference: str,
                description: str, customer: dict, notes: dict) -> tuple[str, str]:
	"""A hosted checkout for one fresh tx_ref. Returns (tx_ref, checkout url)."""
	import requests

	tx_ref = f"{reference}-{frappe.generate_hash(length=10)}"[:50]
	first, _, last = (customer.get("name") or "Guest").strip().partition(" ")
	prop = notes.get("property")
	title = frappe.db.get_value("Property", prop, "property_name") if prop else ""
	body = {
		"amount": _money(amount),
		"currency": currency,
		"tx_ref": tx_ref,
		"first_name": first or "Guest",
		"last_name": last or first or "Guest",
		# Chapa calls this when the checkout finishes; it only prompts a
		# verify, so it needs no signature
		"callback_url": get_url("/api/method/kamra.payments.gateway_callback?gateway=Chapa"),
		"return_url": get_url(f"/pay?tx_ref={tx_ref}"),
		"customization": {"title": _plain(title or "Hotel", 16) or "Hotel",
		                  "description": _plain(description, 50)},
		"meta": {"folio": notes.get("folio") or reference},
	}
	if customer.get("email"):
		body["email"] = customer["email"]
	phone = _local_phone(customer.get("contact"))
	if phone:
		body["phone_number"] = phone
	resp = requests.post(f"{API}/transaction/initialize", json=body,
	                     headers=_auth(settings), timeout=20)
	data = {}
	if resp.status_code < 400:
		try:
			data = resp.json() or {}
		except ValueError:
			data = {}
	url = (data.get("data") or {}).get("checkout_url")
	if data.get("status") != "success" or not url:
		frappe.throw(f"Chapa refused the payment link: {_error(resp)}")
	return tx_ref, url


def test_link(link_id: str) -> str:
	return f"https://checkout.chapa.co/checkout/test/{link_id}"


def info() -> dict:
	return {
		"gateway": GATEWAY,
		"webhook_url": get_url("/api/method/kamra.payments.gateway_webhook?gateway=Chapa"),
		"signup_url": frappe.conf.get("kamra_chapa_signup_url") or SIGNUP_URL,
		"needs_webhook": True,
		"webhook_hint": "In the Chapa dashboard, open Settings → Webhooks, "
		                "paste this URL, and set the same secret hash as the "
		                "webhook secret here:",
		"signup_pitch": "and take telebirr, CBE Birr, M-Pesa, cards and bank "
		                "payments for deposits and bills.",
	}


def check_status(settings, tx_ref: str) -> dict:
	"""What Chapa says happened to a tx_ref: status success / failed /
	pending, with the amount and currency actually paid and Chapa's own
	reference (refunds are made against that, not our tx_ref)."""
	import requests

	resp = requests.get(f"{API}/transaction/verify/{tx_ref}",
	                    headers=_auth(settings), timeout=20)
	try:
		body = resp.json() or {}
	except ValueError:
		body = {}
	if resp.status_code == 404 or (resp.status_code == 400 and not body.get("data")):
		# Chapa answers "transaction not found" until the guest pays
		return {"status": "pending"}
	if resp.status_code >= 400:
		frappe.throw(f"Chapa verify failed: {_error(resp)}")
	data = body.get("data") or {}
	status = str(data.get("status") or "pending").lower()
	if status not in ("success", "failed"):
		status = "pending"
	return {"status": status, "amount": float(data.get("amount") or 0),
	        "currency": (data.get("currency") or "").upper(),
	        "reference": data.get("reference") or ""}


def _event(payload: bytes) -> dict:
	try:
		event = json.loads(payload or b"{}")
	except ValueError:
		return {}
	return event if isinstance(event, dict) else {}


def webhook_folio(payload: bytes) -> str | None:
	tx_ref = _event(payload).get("tx_ref")
	if not tx_ref:  # payouts carry no tx_ref and are not ours to post
		return None
	return frappe.db.get_value("Payment Gateway Transaction",
	                           {"tx_ref": tx_ref, "gateway": GATEWAY}, "folio")


def _signed(secret: str, payload: bytes, given: str) -> bool:
	if not secret or not given:
		return False
	candidates = [payload or b""]
	# Chapa's sample signs JSON.stringify(body): the compact form of the
	# same JSON - accept that too, it binds the same content
	try:
		candidates.append(json.dumps(json.loads(payload), separators=(",", ":"),
		                             ensure_ascii=False).encode())
	except ValueError:
		pass
	return any(hmac.compare_digest(
		given, hmac.new(secret.encode(), c, hashlib.sha256).hexdigest())
		for c in candidates)


def verify_webhook(settings, payload: bytes, headers: dict) -> dict | None:
	"""Check x-chapa-signature (HMAC-SHA256 of the payload with the webhook
	secret), then ask Chapa's verify API what really happened. The payload
	only tells us which tx_ref to ask about. With no webhook secret there
	is nothing to check against, so the call is refused, not trusted - the
	pending sweep still picks the payment up."""
	secret = settings.get_password("webhook_secret", raise_exception=False)
	if not _signed(secret, payload, headers.get("x-chapa-signature") or ""):
		frappe.throw("Invalid webhook signature", frappe.PermissionError)
	event = _event(payload)
	tx_ref = event.get("tx_ref")
	if not tx_ref:
		return None
	name = str(event.get("event") or "")
	if name in ("charge.refunded", "charge.reversed"):
		return {"link_id": tx_ref, "amount": 0, "status": "reversed",
		        "detail": f"Chapa reported {name}"}
	st = check_status(settings, tx_ref)
	return {"link_id": tx_ref, "amount": st.get("amount") or 0,
	        "status": st["status"], "currency": st.get("currency"),
	        "reference": st.get("reference")}


def refund(settings, tx, amount, reason: str) -> str:
	"""Refund against Chapa's reference for the charge. Returns the refund
	reference. Chapa keeps its fee; the refund comes out of the balance."""
	import requests

	if not tx.gateway_reference:
		frappe.throw("This payment has no Chapa reference yet - verify it first.")
	n = len([r for r in (tx.refund_references or "").splitlines() if r.strip()]) + 1
	ref = f"{tx.tx_ref}-R{n}"[:50]
	resp = requests.post(f"{API}/refund/{tx.gateway_reference}",
	                     json={"amount": _money(amount), "reason": reason[:100],
	                           "reference": ref},
	                     headers=_auth(settings), timeout=30)
	data = {}
	if resp.status_code < 400:
		try:
			data = resp.json() or {}
		except ValueError:
			data = {}
	if data.get("status") != "success":
		frappe.throw(f"Chapa refused the refund: {_error(resp)}")
	return (data.get("data") or {}).get("reference") or ref
