// Plain anchors bypass the router's base path. The status API and catalog name console routes without it
// (e.g. `/data/power/load`), so links built from them go through here to stay inside the console.
export function consoleHref(route: string): string {
  return `${import.meta.env.BASE_URL.replace(/\/$/, '')}${route}`
}
