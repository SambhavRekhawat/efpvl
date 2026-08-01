/** Environment-based configuration. Never hardcode URLs in components.
 *
 * Default is the RELATIVE "/api": in single-server mode FastAPI serves both
 * the app and the API from one origin; in dev, Vite proxies /api to :8000.
 * A full URL via VITE_API_BASE_URL still works for split deployments.
 */
export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? "/api";
