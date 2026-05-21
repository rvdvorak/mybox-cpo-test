// API contract shapes and SSE event payloads.
// Mirrors backend Pydantic models (architektura sekce 7) verbatim:
// datetime fields arrive as ISO strings, nullable fields as `| null`.

// --- Station status (architektura 8.2) ----------------------------------

// Known statuses for the color mapping. The API field stays typed as
// `string` below — an unknown value must not break rendering.
export type StationStatus =
  | "Available"
  | "Preparing"
  | "Charging"
  | "Finishing"
  | "Faulted"
  | "Offline";

// --- REST: GET /api/stations (7.1) ---------------------------------------

export interface ActiveSession {
  transaction_id: string;
  start_time: string;
  energy_wh: number;
  power_kw: number;
}

export interface Station {
  station_id: string;
  status: string;
  connector_type: string;
  max_power_kw: number;
  last_heartbeat: string | null;
  active_session: ActiveSession | null;
}

export interface StationsResponse {
  stations: Station[];
}

// --- REST: GET /api/stations/:id (7.2) -----------------------------------

export interface MeterReading {
  ts: string;
  power_kw: number;
  energy_wh: number;
}

export interface StationDetail extends Station {
  firmware_version: string | null;
  monitoring_agent: string | null;
  recent_meter_readings: MeterReading[];
}

// --- REST: GET /api/stations/:id/sessions (7.3) --------------------------

export interface Session {
  transaction_id: string;
  station_id: string;
  start_time: string;
  end_time: string | null;
  duration_seconds: number | null;
  start_meter_wh: number;
  end_meter_wh: number | null;
  total_kwh: number | null;
  total_cost: number | null;
  end_reason: string | null;
}

export interface SessionsResponse {
  sessions: Session[];
  total: number;
}

// --- REST: POST start / stop (7.4, 7.5) ----------------------------------

export interface StartResponse {
  transaction_id: string;
  issued_at: string;
  message: string;
}

export interface StopResponse {
  issued_at: string;
  message: string;
}

// Error envelope: { error, code, current_status? } (architektura 7).
export interface ApiError {
  error: string;
  code: string;
  current_status?: string;
}

// --- SSE event payloads (architektura 7.6) -------------------------------

export interface StatusChangedEvent {
  station_id: string;
  status: string;
  ts: string;
}

export interface MeterEvent {
  station_id: string;
  power_kw: number;
  energy_wh: number;
  ts: string;
}

export interface SessionStartedEvent {
  transaction_id: string;
  station_id: string;
}

export interface SessionEndedEvent {
  transaction_id: string;
  station_id: string;
  end_reason: string | null;
}

export interface HeartbeatEvent {
  station_id: string;
  ts: string;
}
