// Station detail (route `/stations/:id`) — status, controls, chart,
// active session panel (architektura 8.4).

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiClientError, startSession, stopSession } from "../api/apiClient";
import PowerChart from "../components/PowerChart";
import StatusBadge from "../components/StatusBadge";
import { useStationDetail } from "../hooks/useStationDetail";
import { formatDateTime, formatDuration } from "../utils/formatTime";

export default function StationDetailPage() {
  const { id } = useParams();
  const stationId = id ?? "";
  const { detail, meterReadings, loading, error } = useStationDetail(stationId);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Runs a start/stop call, surfacing backend 409/503 as an inline message.
  async function runAction(action: () => Promise<unknown>) {
    setBusy(true);
    setActionError(null);
    try {
      await action();
    } catch (e) {
      if (e instanceof ApiClientError) {
        setActionError(
          e.currentStatus
            ? `${e.message} (current status: ${e.currentStatus})`
            : e.message,
        );
      } else {
        setActionError("Request failed");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl p-6">
      <Link to="/" className="text-sm text-blue-600 hover:underline">
        ← Back to dashboard
      </Link>

      {loading && (
        <p className="mt-4 text-sm text-gray-500">Loading station…</p>
      )}

      {error && (
        <p className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {!loading && !error && detail && (
        <>
          {/* Header */}
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
            <h1 className="font-mono text-2xl font-semibold text-gray-800">
              {detail.station_id}
            </h1>
            <StatusBadge status={detail.status} />
          </div>
          <dl className="mt-3 grid grid-cols-3 gap-3 text-sm">
            <Field label="Connector" value={detail.connector_type} />
            <Field label="Max power" value={`${detail.max_power_kw} kW`} />
            <Field
              label="Firmware"
              value={detail.firmware_version ?? "—"}
            />
          </dl>

          {/* Controls */}
          <div className="mt-5 flex items-center gap-3">
            <button
              onClick={() => runAction(() => startSession(stationId))}
              disabled={busy || detail.status !== "Available"}
              className="rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:cursor-not-allowed disabled:bg-gray-300"
            >
              Start
            </button>
            <button
              onClick={() => runAction(() => stopSession(stationId))}
              disabled={busy || detail.status !== "Charging"}
              className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:bg-gray-300"
            >
              Stop
            </button>
          </div>
          {actionError && (
            <p className="mt-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
              {actionError}
            </p>
          )}

          {/* Power / energy chart */}
          <h2 className="mt-6 mb-2 text-sm font-medium text-gray-500">
            Power &amp; energy (last 5 min)
          </h2>
          <PowerChart readings={meterReadings} />

          {/* Active session panel — only while charging */}
          {detail.status === "Charging" && detail.active_session && (
            <div className="mt-5 rounded-lg border border-blue-200 bg-blue-50 p-4">
              <h2 className="mb-2 text-sm font-medium text-blue-800">
                Active session
              </h2>
              <dl className="grid grid-cols-2 gap-2 text-sm">
                <Field
                  label="Transaction ID"
                  value={detail.active_session.transaction_id}
                  mono
                />
                <Field
                  label="Started"
                  value={formatDateTime(detail.active_session.start_time)}
                />
                <Field
                  label="Energy"
                  value={`${detail.active_session.energy_wh} Wh`}
                />
                <Field
                  label="Duration"
                  value={formatDuration(
                    (Date.now() -
                      new Date(detail.active_session.start_time).getTime()) /
                      1000,
                  )}
                />
              </dl>
            </div>
          )}

          {/* History link */}
          <Link
            to={`/stations/${stationId}/sessions`}
            className="mt-5 inline-block text-sm text-blue-600 hover:underline"
          >
            Zobrazit historii sessions →
          </Link>
        </>
      )}
    </div>
  );
}

interface FieldProps {
  label: string;
  value: string;
  mono?: boolean;
}

function Field({ label, value, mono }: FieldProps) {
  return (
    <div>
      <dt className="text-xs text-gray-500">{label}</dt>
      <dd className={`text-gray-800 ${mono ? "font-mono break-all" : ""}`}>
        {value}
      </dd>
    </div>
  );
}
