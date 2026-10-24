"""Ethiopia localization pack.

Hotel rooms, hotel F&B and guest services are standard-rated VAT supplies
at 15%. This first cut is a flat-rate pack, like Thailand:

  - the rate comes from the Room Type's tax percent (default 15), so if
    the statutory rate changes the operator types the new number on the
    room type
  - the customary service charge is NOT VAT; it is optional per property
    and arrives with the Ethiopian tax engine, together with TOT mode for
    non-VAT-registered properties and zero-rated exemptions
  - tax invoices quote the seller's TIN and say "Tax Invoice"

Settles in Birr (ETB, 2 decimals). No fiscal-device or e-invoicing
integration for now; the e-invoicing hooks stay unimplemented.

Ethiopia-only integrations (the Chapa gateway) will sit beside this file.
"""

from decimal import Decimal

import frappe

DEFAULT_VAT = Decimal("15")

DEFAULT_CURRENCY = "ETB"
DEFAULT_TIMEZONE = "Africa/Addis_Ababa"
DEFAULT_NATIONALITY = "Ethiopian"
# named in the guest privacy notice (Personal Data Protection Proclamation
# No. 1321/2024) - to be reviewed with the privacy work
PRIVACY_AUTHORITY = "the Ethiopian Communications Authority"
GUEST_REPORT = "the hotel guest register, kept for inspection by the police and immigration authorities"
# what the front desk records at check-in; a property can replace the list
# under its own ID types
ID_TYPES = ["Fayda National ID", "Kebele ID", "Passport", "Residence Permit",
            "Driving Licence"]
PAYMENT_MODES = ["Cash", "Card", "Bank Transfer"]
# the guest register is a paper-and-signature habit; the guided check-in
# asks for the GRC by default, a property can still change its steps
REGISTRATION_CARD_REQUIRED = True

# Mobile numbers: +251 then 9 digits, 9xxxxxxxx (Ethio telecom) or
# 7xxxxxxxx (Safaricom Ethiopia). Guest contact is SMS-first, so a landline
# is refused as a guest's phone.
DIAL_CODE = "251"
MOBILE_PREFIXES = ("9", "7")
NATIONAL_LENGTH = 9


def validate_phone(national: str) -> str | None:
	"""Why this national number (digits after +251) is not an Ethiopian
	mobile number, or None when it is."""
	n = national[1:] if national.startswith("0") else national
	if len(n) != NATIONAL_LENGTH or not n.startswith(MOBILE_PREFIXES):
		return ("An Ethiopian mobile number is +251 followed by 9 digits "
		        "starting with 9 or 7, e.g. +251 911 234 567.")
	return None


def calculate_room_tax(property, room_type_doc, nightly_rate) -> Decimal:
	"""Flat VAT - unset means the standard 15%."""
	v = room_type_doc.get("tax_percent") if room_type_doc else None
	return Decimal(str(v)) if v else DEFAULT_VAT


def fnb_tax_rate(property) -> float:
	"""Hotel restaurants are the same standard-rated VAT supply."""
	rates = frappe.get_all(
		"Room Type", filters={"property": property, "disabled": 0},
		pluck="tax_percent", limit=5)
	first = next((r for r in rates if r), None)
	return float(first) if first else float(DEFAULT_VAT)


def tax_rate_options(property) -> list:
	return [0, 15]


def invoice_context(prop_doc) -> dict:
	return {
		"tax_label": "VAT",
		"tax_id_label": "TIN",
		"service_code": None,
		"sac": None,
		"place_of_supply": prop_doc.get("city") or prop_doc.get("state"),
		# national VAT, single line
		"split": [("vat", Decimal("1"))],
		"footer": "Tax Invoice - This is a computer-generated invoice.",
	}


def locale(prop_doc) -> dict:
	return {
		# trailing space: "Br 1,500" - the UI concatenates symbol+amount
		"currency_symbol": "Br ",
		"locale": "en-ET",
		"currency": prop_doc.get("currency") or DEFAULT_CURRENCY,
		"tax_label": "VAT",
		"tax_id_label": "TIN",
		"tax_rates": tax_rate_options(prop_doc.name),
	}
