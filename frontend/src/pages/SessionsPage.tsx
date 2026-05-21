// Sessions history (route `/stations/:id/sessions`) — paginated table
// (architektura 8.5).

import { Link, useParams } from "react-router-dom";
import { useStationSessions } from "../hooks/useStationSessions";
import { formatDateTime, formatDuration } from "../utils/formatTime";

export default function SessionsPage() {
  const { id } = useParams();
  const stationId = id ?? "";
  const { sessions, total, loading, loadingMore, error, hasMore, loadMore } =
    useStationSessions(stationId);

  return (
    <div className="mx-auto max-w-4xl p-6">
      <Link
        to={`/stations/${stationId}`}
        className="text-sm text-blue-600 hover:underline"
      >
        ← Back to station
      </Link>

      <h1 className="mt-3 mb-4 text-2xl font-semibold text-gray-800">
        <span className="font-mono">{stationId}</span> — sessions
      </h1>

      {loading && <p className="text-sm text-gray-500">Loading sessions…</p>}

      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {!loading && !error && (
        <>
          {sessions.length === 0 ? (
            <p className="text-sm text-gray-500">No sessions recorded.</p>
          ) : (
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-left text-gray-500">
                  <th className="py-2 pr-4 font-medium">Start time</th>
                  <th className="py-2 pr-4 font-medium">End time</th>
                  <th className="py-2 pr-4 font-medium">Duration</th>
                  <th className="py-2 pr-4 font-medium">Energy</th>
                  <th className="py-2 pr-4 font-medium">Cost</th>
                  <th className="py-2 pr-4 font-medium">End reason</th>
                </tr>
              </thead>
              <tbody>
                {sessions.map((s) => (
                  <tr
                    key={s.transaction_id}
                    className="border-b border-gray-100"
                  >
                    <td className="py-2.5 pr-4 text-gray-700">
                      {formatDateTime(s.start_time)}
                    </td>
                    <td className="py-2.5 pr-4 text-gray-700">
                      {s.end_time ? formatDateTime(s.end_time) : "—"}
                    </td>
                    <td className="py-2.5 pr-4 text-gray-700">
                      {formatDuration(s.duration_seconds)}
                    </td>
                    <td className="py-2.5 pr-4 text-gray-700">
                      {s.total_kwh != null
                        ? `${s.total_kwh.toFixed(3)} kWh`
                        : "—"}
                    </td>
                    <td className="py-2.5 pr-4 text-gray-700">
                      {s.total_cost != null
                        ? `${s.total_cost.toFixed(2)} CZK`
                        : "—"}
                    </td>
                    <td className="py-2.5 pr-4 text-gray-700">
                      {s.end_reason ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {hasMore && (
            <button
              onClick={loadMore}
              disabled={loadingMore}
              className="mt-4 rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loadingMore ? "Loading…" : "Load more"}
            </button>
          )}

          {sessions.length > 0 && (
            <p className="mt-3 text-xs text-gray-400">
              Showing {sessions.length} of {total}
            </p>
          )}
        </>
      )}
    </div>
  );
}
