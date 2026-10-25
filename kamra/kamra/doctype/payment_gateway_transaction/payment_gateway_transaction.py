# Copyright (c) 2026, Kamra and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PaymentGatewayTransaction(Document):
	"""One attempt to collect money through an online gateway - one payment
	link or hosted checkout. kamra.payments owns every state change."""
	pass
