# StayDesk Ethiopia – open questions

Business, legal and tax decisions for the product owner. Until a question
is answered, the code uses the **safe default** shown, and that default is
configurable data – never a hard-coded constant.

| # | Question | Safe default until answered | Status |
|---|---|---|---|
| 1 | Is Chapa the only gateway at launch, or Chapa + Telebirr direct? | Chapa only; Telebirr direct designed behind the same provider interface, not built | Open |
| 2 | Which exchange-rate source: NBE, CBE, another bank, or manual daily entry? | Manual daily entry by Finance; stale-rate warning after 1 day | Open |
| 3 | Is VAT charged on top of the service charge? Is the service charge 10% everywhere? | Service charge 10%, VAT on (price + service charge), both per-property settings | Open – needs accountant |
| 4 | Which properties are VAT-registered and which are on TOT? | Per-property switch, default VAT-registered | Open |
| 5 | Which Ministry of Revenue fiscal / sales-register / e-invoice requirements apply to the pilot hotels? | No fiscal integration; research in `TAX_COMPLIANCE.md` | Open – needs accountant |
| 6 | What are the guest / foreigner registration reporting requirements and format? | Daily in-house guest register report, foreign guests flagged, CSV export | Open – needs legal |
| 7 | Which SMS provider (Ethio telecom bulk SMS, AfroMessage, GeezSMS)? Telegram bot at launch? | Pluggable SMS adapter, no provider enabled; Telegram off | Open |
| 8 | Hosting: cloud (which region/provider?) or on-premise per hotel? | Document both; no default | Open |
| 9 | Do we contribute the Ethiopia pack upstream to Kamra? | Build as if we will: pack-only code, small generic core seams | Open |
| 10 | Upstream's `feat/online-advance-payments` (booking-engine checkout) is 477 commits behind `develop`. Ask upstream if a rebased version is planned, or build our own gateway-neutral version and offer it back? | Ask upstream first; Chapa provider work proceeds in parallel | Open |
| 11 | Branding: how far does "StayDesk" go – UI, invoices, emails, docs? Is "Kamra" a trademark that requires removal or attribution? AGPL notices stay regardless. | StayDesk in user-facing text only; code stays `kamra`; licence and copyright notices untouched | Open |
| 12 | Should front-desk staff take telebirr / CBE Birr directly (outside Chapa) at the counter? That needs a new canonical payment mode in core. | No: mobile money via Chapa link/QR; desk records Cash, Card, Bank Transfer | Open |
