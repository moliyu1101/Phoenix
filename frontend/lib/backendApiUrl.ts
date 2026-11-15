/** Resolve API requests against the backend configured when the UI starts. */
export function backendApiUrl(
  pathname: string,
  search = "",
  backend = process.env.PHOENIX_BACKEND || "http://127.0.0.1:18750",
): URL {
  const url = new URL(backend);
  url.pathname = pathname;
  url.search = search;
  url.hash = "";
  return url;
}
