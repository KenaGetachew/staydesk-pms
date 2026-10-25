import { useEffect, useState } from "react"
import { call } from "../lib/api"
import { cur, moneyLocale } from "../lib/money"
import { useT } from "../lib/i18n"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"

/** Online payment attempts on a folio (payment links, hosted checkouts):
 *  each link's state as the gateway reported it, and a refund back through
 *  the gateway for money that came in that way. Amounts and limits are the
 *  server's; this panel only shows them and asks. */

type GatewayTxn = {
  name: string
  gateway: string
  purpose: string | null
  status: "Pending" | "Success" | "Failed" | "Expired" | "Partly Refunded" | "Refunded"
  amount: number
  currency: string
  refunded_amount: number
  gateway_reference: string | null
  simulated: 0 | 1
  sandbox: 0 | 1
  creation: string
  status_detail: string | null
}

const TONE = {
  Pending: "amber",
  Success: "green",
  Failed: "rose",
  Expired: "zinc",
  "Partly Refunded": "sky",
  Refunded: "sky",
} as const

export default function GatewayPayments({ folio, open, version, busy, act }: {
  folio: string
  open: boolean
  /** changes whenever the folio reloads, so the list follows it */
  version: string
  busy: boolean
  act: (fn: () => Promise<unknown>) => Promise<void>
}) {
  const { t } = useT()
  const [rows, setRows] = useState<GatewayTxn[]>([])
  const [refund, setRefund] = useState<{ link: string; amount: string; reason: string } | null>(null)

  useEffect(() => {
    call<GatewayTxn[]>("kamra.payments.gateway_transactions", { folio })
      .then(setRows).catch(() => setRows([]))
  }, [folio, version])

  if (!rows.length) return null
  const money = (n: number) =>
    Number(n || 0).toLocaleString(moneyLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })

  return (
    <div className="mt-6 text-sm print:hidden">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">
        {t("Online payments")}
      </h3>
      <ul className="divide-y divide-zinc-100">
        {rows.map((r) => {
          const left = Number(r.amount) - Number(r.refunded_amount || 0)
          const refundable = open && left > 0 && (r.status === "Success" || r.status === "Partly Refunded")
          return (
            <li key={r.name} className="py-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="min-w-0">
                  {r.creation.slice(0, 10)} · {r.gateway}
                  {r.purpose && <span className="text-zinc-500"> · {t(r.purpose)}</span>}
                  <Badge tone={TONE[r.status]} className="ml-1.5">{t(r.status)}</Badge>
                  {(r.simulated || r.sandbox) ? (
                    <span className="ml-1.5 text-[10px] font-semibold uppercase text-amber-700">{t("test")}</span>
                  ) : null}
                  <span className="block truncate text-xs text-zinc-400">
                    {r.name}{r.gateway_reference ? ` · ${r.gateway_reference}` : ""}
                    {r.status_detail ? ` · ${r.status_detail}` : ""}
                  </span>
                </span>
                <span className="shrink-0 text-right tabular-nums">
                  {cur()}{money(r.amount)}
                  {Number(r.refunded_amount) > 0 && (
                    <span className="block text-xs text-rose-600">−{cur()}{money(r.refunded_amount)}</span>
                  )}
                </span>
              </div>
              {refundable && refund?.link !== r.name && (
                <button className="mt-0.5 text-xs font-medium text-rose-600 hover:underline"
                  onClick={() => setRefund({ link: r.name, amount: String(left), reason: "" })}>
                  {t("Refund through {gateway}", { gateway: r.gateway })}
                </button>
              )}
              {refund?.link === r.name && (
                <div className="mt-2 flex flex-wrap items-end gap-2 rounded-lg border border-rose-200 bg-rose-50 p-2">
                  <input className="w-28 rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm"
                    type="number" min={0} max={left} step="0.01" aria-label={t("Amount")}
                    value={refund.amount} onChange={(e) => setRefund({ ...refund, amount: e.target.value })} />
                  <input className="min-w-40 flex-1 rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm"
                    placeholder={t("Reason (required)")} value={refund.reason}
                    onChange={(e) => setRefund({ ...refund, reason: e.target.value })} />
                  <Button variant="outline" className="text-rose-600"
                    disabled={busy || !Number(refund.amount) || !refund.reason.trim()}
                    onClick={() => act(async () => {
                      await call("kamra.payments.refund_gateway_payment", {
                        folio, link_id: r.name, amount: Number(refund.amount), reason: refund.reason,
                      })
                      setRefund(null)
                    })}>
                    {t("Refund")}
                  </Button>
                  <Button variant="ghost" onClick={() => setRefund(null)}>✕</Button>
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
