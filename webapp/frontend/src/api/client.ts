export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) throw new ApiError(res.status, await res.text());
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function buildUrl(path: string, params?: Record<string, unknown>): string {
  const url = new URL(path, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === "") continue;
      if (Array.isArray(value)) value.forEach((v) => url.searchParams.append(key, String(v)));
      else url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

export function apiGet<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  return fetch(buildUrl(path, params)).then((r) => handle<T>(r));
}

export function apiPost<T>(path: string, body?: unknown, params?: Record<string, unknown>): Promise<T> {
  return fetch(buildUrl(path, params), {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then((r) => handle<T>(r));
}

export function apiDelete(path: string, params?: Record<string, unknown>): Promise<void> {
  return fetch(buildUrl(path, params), { method: "DELETE" }).then((r) => handle<void>(r));
}
