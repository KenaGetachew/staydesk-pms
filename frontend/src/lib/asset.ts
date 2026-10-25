// Resolve a static asset shipped in frontend/public against the build base.
// Dev: BASE_URL is "/", so asset("staydesk-mark.svg") -> "/staydesk-mark.svg".
// Prod: BASE_URL is "/assets/kamra/frontend/", so the same call resolves to
// "/assets/kamra/frontend/staydesk-mark.svg" (where Frappe serves it).
export const asset = (path: string) =>
  import.meta.env.BASE_URL + path.replace(/^\//, "")
