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


def run():
	for fn in (e1, e2, e3):
		fn()
