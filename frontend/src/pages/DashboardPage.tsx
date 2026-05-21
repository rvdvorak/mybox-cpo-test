// Dashboard (route `/`) — live fleet overview table (architektura 8.3).

import { useNavigate } from "react-router-dom";
import StatusBadge from "../components/StatusBadge";
import { useStationsLive } from "../hooks/useStationsLive";
import { relativeTime } from "../utils/formatTime";

export default function DashboardPage() {
  const navigate = useNavigate();
  const { stations, loading, error } = useStationsLive();

  return (
    <div className="mx-auto max-w-4xl p-6">
      <h1 className="mb-4 text-2xl font-semibold text-gray-800">
        Charging Stations
      </h1>

      {loading && <p className="text-sm text-gray-500">Loading stations…</p>}

      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {!loading && !error && (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-left text-gray-500">
              <th className="py-2 pr-4 font-medium">Station ID</th>
              <th className="py-2 pr-4 font-medium">Status</th>
              <th className="py-2 pr-4 font-medium">Power</th>
              <th className="py-2 pr-4 font-medium">Last heartbeat</th>
            </tr>
          </thead>
          <tbody>
            {stations.map((s) => (
              <tr
                key={s.station_id}
                onClick={() => navigate(`/stations/${s.station_id}`)}
                className="cursor-pointer border-b border-gray-100 hover:bg-gray-50"
              >
                <td className="py-2.5 pr-4 font-mono text-gray-800">
                  {s.station_id}
                </td>
                <td className="py-2.5 pr-4">
                  <StatusBadge status={s.status} />
                </td>
                <td className="py-2.5 pr-4 text-gray-700">
                  {s.status === "Charging" && s.active_session
                    ? `${s.active_session.power_kw.toFixed(1)} kW`
                    : "—"}
                </td>
                <td className="py-2.5 pr-4 text-gray-600">
                  {relativeTime(s.last_heartbeat)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
