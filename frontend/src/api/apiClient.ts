// REST client for the CPO backend (architektura sekce 7).
// Backend URL is injected via VITE_API_URL; falls back to the local default.

import type {
  ApiError,
  SessionsResponse,
  StartResponse,
  StationDetail,
  StationsResponse,
  StopResponse,
} from "../types";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:3000";

// Carries the parsed backend error envelope so callers (e.g. the detail
// page) can render code-specific inline messages for 404 / 409 / 503.
export class ApiClientError extends Error {
  status: number;
  code: string;
  currentStatus?: string;

  constructor(status: number, body: Partial<ApiError>) {
    super(body.error ?? `Request failed with status ${status}`);
    this.name = "ApiClientError";
    this.status = status;
    this.code = body.code ?? "UNKNOWN";
    this.currentStatus = body.current_status;
  }
}

// Parses a fetch Response; throws ApiClientError on non-2xx, otherwise
// returns the JSON body. Tolerates an empty or non-JSON error body.
async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let body: Partial<ApiError> = {};
    try {
      body = await res.json();
    } catch {
      // non-JSON error body — keep the empty envelope
    }
    throw new ApiClientError(res.status, body);
  }
  return res.json() as Promise<T>;
}

export function getStations(): Promise<StationsResponse> {
  return fetch(`${BASE}/api/stations`).then((res) =>
    parse<StationsResponse>(res),
  );
}

export function getStation(stationId: string): Promise<StationDetail> {
  return fetch(`${BASE}/api/stations/${encodeURIComponent(stationId)}`).then(
    (res) => parse<StationDetail>(res),
  );
}

export function getSessions(
  stationId: string,
  limit: number,
  offset: number,
): Promise<SessionsResponse> {
  const url =
    `${BASE}/api/stations/${encodeURIComponent(stationId)}/sessions` +
    `?limit=${limit}&offset=${offset}`;
  return fetch(url).then((res) => parse<SessionsResponse>(res));
}

export function startSession(stationId: string): Promise<StartResponse> {
  return fetch(`${BASE}/api/stations/${encodeURIComponent(stationId)}/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  }).then((res) => parse<StartResponse>(res));
}

export function stopSession(stationId: string): Promise<StopResponse> {
  return fetch(`${BASE}/api/stations/${encodeURIComponent(stationId)}/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  }).then((res) => parse<StopResponse>(res));
}

// SSE endpoint URL — consumed by useSSE via EventSource.
export const SSE_URL = `${BASE}/api/stream/events`;
