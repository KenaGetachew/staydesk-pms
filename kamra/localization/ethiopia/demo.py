"""Demo Addis Ababa hotel on the Ethiopia pack.

Created through setup_property - the same call the onboarding wizard
makes - so the country defaults (ETB, Africa/Addis_Ababa) come from the
pack exactly as they would for a real hotel. Idempotent.

    bench --site <site> execute kamra.localization.ethiopia.demo.execute
"""

import frappe
from frappe.utils import add_days, nowdate

PROPERTY = "StayDesk Addis Hotel"

ROOM_TYPES = [
	{"code": "STD", "name": "Standard Room", "base_price": 6500,
	 "extra_adult_price": 1500, "adults": 2, "children": 1},
	{"code": "DLX", "name": "Deluxe Room", "base_price": 9000,
	 "extra_adult_price": 2000, "adults": 2, "children": 1},
	{"code": "STE", "name": "Executive Suite", "base_price": 15000,
	 "extra_adult_price": 2500, "adults": 3, "children": 2},
]
ROOMS = [
	{"room_type_code": "STD", "numbers": ["101", "102", "103", "104", "201", "202"]},
	{"room_type_code": "DLX", "numbers": ["203", "204", "301", "302"]},
	{"room_type_code": "STE", "numbers": ["401", "402"]},
]
MEAL_PLANS = [{"code": "CP", "label": "Bed & Breakfast", "price_per_adult": 900}]

# (guest, phone, nationality, room type, arrives in N days, nights)
STAYS = [
	("Abebe Kebede", "+251911234567", "Ethiopian", "STD", 0, 2),
	("Hanna Tesfaye", "+251722345678", "Ethiopian", "DLX", 1, 3),
	("Sarah Johnson", "+447700900123", "British", "STE", 2, 4),
]


def execute():
	from kamra.api import create_booking, setup_property

	if not frappe.db.exists("Property", PROPERTY):
		setup_property({
			"property": {
				"property_name": PROPERTY,
				"city": "Addis Ababa",
				"state": "Addis Ababa",
				"country": "Ethiopia",
				"phone": "+251115500100",
				"email": "addis@staydesk.local",
				"checkin_time": "14:00:00",
				"checkout_time": "12:00:00",
			},
			"room_types": ROOM_TYPES,
			"rooms": ROOMS,
			"meal_plans": MEAL_PLANS,
		})
		print(f"Seeded demo property '{PROPERTY}'.")

	room_types = {
		rt.room_type_code: rt.name for rt in frappe.get_all(
			"Room Type", filters={"property": PROPERTY},
			fields=["name", "room_type_code"])}
	for guest, phone, nationality, code, offset, nights in STAYS:
		if frappe.db.exists("Reservation", {"property": PROPERTY,
		                                    "guest_name": guest}):
			continue
		arrive = add_days(nowdate(), offset)
		booking = create_booking(PROPERTY, room_types[code], arrive,
		                         add_days(arrive, nights), guest, phone=phone)
		frappe.db.set_value("Guest", booking["guest"], "nationality",
		                    nationality)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- batch/seed/migration script runs outside the request cycle; explicit commit persists the staged writes
	print(f"Demo stays ready on '{PROPERTY}'.")
