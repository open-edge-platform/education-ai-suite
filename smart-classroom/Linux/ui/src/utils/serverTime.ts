// metrics-collector (performance-tools) emits naive timestamps off the
// container clock, which defaults to UTC with no TZ set. Without an explicit
// offset, `new Date(...)` would read them as already-local and misrender by
// the host/browser's UTC offset, so tag them 'Z' here before parsing.
export function parseServerTimestamp(ts: string): Date {
  return new Date(/Z$|[+-]\d{2}:\d{2}$/.test(ts) ? ts : `${ts}Z`);
}
