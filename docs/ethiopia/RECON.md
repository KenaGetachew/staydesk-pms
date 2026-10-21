# StayDesk Ethiopia – Phase 0 recon

Extension-point map for the Ethiopia country pack, read against upstream
`develop` @ `97476cd9` (2026-10). File references are `path:line` on that
commit. Items marked **(verify)** still need confirming on a running site.

## 1. Country pack seam (`kamra/localization/__init__.py`)

Packs are plain modules mapped by country name in `kamra/hooks.py:87`
(`kamra_localization`). `pack_for(property)` reads `Property.country`;
unknown countries fall back to `generic.py`. Note `pack_for` defaults a
property with **no** country to India (`__init__.py:38`) – our demo and
setup must always set `country = "Ethiopia"`.

| Pack member | Required | What it drives | Ethiopia use |
|---|---|---|---|
| `calculate_room_tax(property, room_type_doc, nightly_rate)` | yes | room-night tax % (Decimal) | VAT 15% / TOT / exempt |
| `fnb_tax_rate(property)` | yes | POS / F&B tax % | VAT 15% |
| `tax_rate_options(property)` | yes | rates offered in settings | `[0, 15]` + TOT rates |
| `invoice_context(prop_doc)` | yes | labels, split, footer | "Tax Invoice", TIN |
| `locale(prop_doc)` | yes | currency symbol, locale, tax label | `Br `, `en-ET`, ETB |
| `services_tax_rate` | no | laundry / services | VAT 15% |
| `service_code_for`, `tax_split`, `amount_in_words` | no | invoice printing | words in Birr/santim |
| `ID_TYPES`, `PAYMENT_MODES`, `DEFAULT_*`, `ADULT_AGE`, `MINOR_IDS`, `REGISTRATION_CARD_REQUIRED` | no | desk vocabulary | Fayda, Kebele ID… |
| `PRIVACY_AUTHORITY`, `GUEST_REPORT`, `NOTICE_LANGUAGES` | no | privacy notice | PDP Proclamation, `am` |
| `PAYMENT_GATEWAYS` + `payment_provider(gateway)` | no | online payments | **Chapa** |
| `tax_return_rows` | no | tax-return export | monthly VAT report |
| `on_invoice_issued` / `on_invoice_cancelled` / `on_pos_bill_paid` / `invoice_print_block` | no | e-invoicing (ZATCA pattern) | MoR, if required |

Smallest pack to copy: `thailand.py`. Integrations reference: `india/`.
E-invoicing reference: `saudi.py` → `kamra/zatca/`.

**Gap – tax model.** The seam returns *one rate per line*. It has no
concept of a separate **service charge** line, VAT-on-service-charge, TOT
mode, or exemption with reason/reference. `Property` has generic
`rates_include_tax`, `cleaning_fee_taxable`, `room_levy_taxable`, but the
rate fields are India-named (`gst_mode`, `gst_rate_low/high`,
`gst_slab_threshold`). `generic.py` reuses `gst_rate_low` as its VAT %.
Saudi/UAE post levies "as a normal folio charge line" – service charge may
fit the existing room-levy mechanism **(verify `room_levy_*` behaviour)**.
Phase 4 needs a design spike before code.

## 2. Payments

### How a gateway plugs in today
- Provider module interface (from `india/razorpay.py`, `india/cashfree.py`):
  `create_link(settings, *, amount, currency, reference, description, customer, notes) -> (id, url)`,
  `test_link(id)`, `info()`, `webhook_folio(payload)`, `verify_webhook(settings, payload, headers) -> {link_id, amount}`.
- Core flow, `kamra/payments.py`:
  - `create_payment_link(folio, amount=None, purpose)` – amount defaults to
    the folio balance (server side); stamps `payment_link_id/url/amount` on
    the Folio.
  - `handle_webhook` → `loc.parse_payment_webhook` → `settle_payment_link`,
    idempotent on `reference == link_id` among the folio's payments.
  - `settle_payment_link` posts a `Folio Payment` (`mode = "Payment Link"`,
    kind `Advance` pre-arrival else `Payment`), recalculates, writes the
    ledger, bumps `Reservation.advance_paid`, confirms Held / Pending
    Payment bookings, and logs via `savings.log_action`.
  - Webhook endpoints are **one whitelisted function per gateway** in core
    (`razorpay_webhook`, `cashfree_webhook`).
- Callers: `api.deposit_payment_link` (staff, deposit due by default or a
  staff-entered amount), `api.folio_payment_link`, `api.simulate_payment_link`
  (test mode), `whatsapp.send_payment_request`.
- Settings: `Payment Gateway Settings` doctype – `property`, `gateway`
  (Select **hard-coded `Razorpay|Cashfree`**), `enabled`, `test_mode`,
  `key_id`, `key_secret` (Password), `webhook_secret` (Password).
- The Frappe `payments` app is installed but no longer on the live path:
  upstream commit `8b6e8980` notes it used one site-wide account and never
  set `notes.folio`. Packs talk to gateways directly with per-property keys.

### Gaps for Chapa (plan §2.1)
| Need | Today | Proposed |
|---|---|---|
| Gateway in settings | Select is `Razorpay\|Cashfree` | Small core change: add `Chapa` (or derive options from packs – upstreamable) |
| Webhook endpoint | per-gateway function in core | Small core change: one generic `gateway_webhook(gateway)` *or* a `chapa_webhook` beside the others |
| Webhook trust | amount taken from the signed payload | Chapa: verify HMAC **and** call `GET /transaction/verify/{tx_ref}`; post the verified amount |
| `tx_ref` per attempt, state history (pending/success/failed/expired/refunded), Chapa reference for refunds | single `payment_link_id` on Folio; no states | Pack doctype `Chapa Transaction` keyed by `tx_ref` |
| Test mode | Kamra test mode = **fake link, no API call**, settle via simulator | Chapa has real test keys; need "sandbox" (real call, test keys) distinct from the offline simulator |
| Verify sweep for missed webhooks | none | Pack scheduled job (via `scheduler_events`) |
| Gateway refunds | `api.refund_folio_payment` refunds via till modes only | Provider `refund(...)` + core hook, or pack-only refund endpoint |
| Booking-engine checkout (`/book`) | `public_api.book` computes `advance_due` and sets *Pending Payment* but **never sends the guest to pay** | See below |
| Late payment after hold expiry | `reservation_state.expire_holds` releases Pending Payment every 15 min | Must not auto-confirm a released room; log for a person (rebook/refund) |

**Upstream branch `feat/online-advance-payments` (`8b6e8980`)** adds
exactly the `/book` → gateway checkout (`payments.create_advance_link`,
late-payment handling, eval t77) but is **477 commits behind `develop`**
and predates the pack-based `payments.py`. Treat it as a design reference;
ask upstream whether a rebased version is coming before we build our own
(see OPEN_QUESTIONS Q10).

### Manual / offline modes (plan §2.2)
- `CANONICAL_PAYMENT_MODES = ("Cash", "Card", "UPI", "Bank Transfer")`
  (`__init__.py:130`); `Folio Payment.mode` options add `OTA Prepaid`,
  `Company Credit`, `Payment Link`. A pack can only *choose* from these.
  Ethiopia uses `Cash, Card, Bank Transfer`; mobile money arrives via Chapa
  (`Payment Link`). Direct telebirr/CBE Birr at the desk would need a new
  canonical mode – a core change, deferred.
- `api.add_folio_payment` / deposits require cashier PIN and an open till
  (`api.py:805`).
- **Gap:** no "unverified" payment state, no receipt attachment, no
  approval queue, no configurable bank list. Needs a pack doctype
  (`Bank Transfer Claim`) that posts a normal `Bank Transfer` payment only
  on approval – keeps core untouched.
- Foreign cash: `Folio Payment` already has `currency`, `fx_amount`,
  `exchange_rate`; `ledger.py:1320–1440` has an `Exchange Rate` doctype
  (per property, buy/sell, `rate_date`), `currency_calculator`,
  `post_exchange`. **Reuse for Phase 3** **(verify how a folio payment in
  USD uses it)**.
- City ledger / company billing exists (`Company Credit`, `credit.py`,
  `ledger.py`) **(verify with ETB pack)**.

## 3. Currency
Single currency per property (`Property.currency`, Link to Currency).
Money in core is mostly `float` with `round(…, 2)`; tax rates are
`Decimal`. New pack code will use `Decimal` and convert at the core
boundary. Dual-currency display is not present – Phase 3 design.

## 4. Night audit (plan §2.4)
`kamra/night_audit.py` – checks are functions built with `_check(key,
title, severity, items, action)`; severity per property setting. **(verify)**
whether packs can register checks; if not, add a small extension point so
the pack contributes "pending Chapa / unverified transfers".

## 5. Messaging (for SMS / Telegram, Phase 5)
`kamra/whatsapp.py`: `_conn(property)` → `_post_graph` → `_log` (message
log); public `send_text`, `send_template`, `has_connection`, and business
helpers `notify_booking_confirmed`, `send_payment_request`; inbound
`webhook` with Meta signature check. Business helpers are WhatsApp-specific
– a channel-neutral `notify(...)` interface will be needed.

## 6. Translations (for Amharic, Phase 6)
- React: `frontend/src/i18n/catalog.csv` (columns `key,english,arabic,…` –
  **Arabic is a hard-coded column**) → `locales/ar.json`. Adding `am` needs
  a catalog tooling change (upstreamable: generic language columns).
- Privacy notice: `frontend/src/i18n/notice/<code>.json`, offered via the
  pack's `NOTICE_LANGUAGES`.
- RTL handling present in several screens (Arabic); Amharic is LTR.
- Frappe-side translations **(verify)**.

## 7. Eval harness
`kamra/scripts/eval_harness.py` – 262 `@check` functions, run in a
savepoint and rolled back; CI (`.github/workflows/ci.yml:102`) requires
all green. Checks run from **one hand-written tuple** at the end of the
file, so every addition there is a merge-conflict hotspot. Proposal: put
Ethiopia checks in `kamra/scripts/eval_ethiopia.py` and add one small,
upstreamable hook so the harness also runs checks registered by packs.
Gateway HTTP is mocked by patching `requests` in the check (existing
Razorpay checks around line 2783–2880 show the pattern).

## 8. Environment notes
- Frappe v16.25.0 requires **Python 3.14** and **Node ≥ 24**; MariaDB 11.4.
- Bench layout: `staydesk-ethiopia/frappe-bench`, with `apps/kamra` linked
  to the fork checkout `staydesk-ethiopia/staydesk-pms`.
- Baseline eval result: _pending – recorded once the dev site is up._

## 9. Changes proposed to the plan
1. **Phase 2 depends on upstream's booking-engine checkout.** Ask upstream
   first (Q10); otherwise build a gateway-neutral version in core as a
   small PR we can offer back.
2. **Three small core extension points** are needed before Chapa: gateway
   options not hard-coded, a generic webhook endpoint, and an optional
   provider `refund` / `verify` in the seam. Each is upstreamable.
3. **Phase 4 needs a design spike** – the pack seam has no service-charge
   or TOT concept; decide between the room-levy mechanism and a new
   optional pack hook.
4. **Pack evals in their own file** with a registration hook (above).
5. **Branding:** user-facing name StayDesk; internal app/module stays
   `kamra` to keep merges cheap (Q11).
