// Dashboard data hook (architektura 8.6).
// Combines the initial GET /api/stations fetch with live SSE updates.

import { useCallback, useEffect, useState } from "react";
import { getStations, SSE_URL } from "../api/apiClient";
import type {
  HeartbeatEvent,
  MeterEvent,
  Station,
  StatusChangedEvent,
} from "../types";
import { useSSE } from "./useSSE";

export function useStationsLive() {
  const [stations, setStations] = useState<Station[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Re-fetch the whole list — used on session boundary events, where the
  // SSE payload alone cannot reconstruct active_session.
  const refetch = useCallback(() => {
    getStations()
      .then((res) => {
        setStations(res.stations);
        setError(null);
      })
      .catch((e) => setError(e.message ?? "Failed to load stations"));
  }, []);

  // Initial load.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getStations()
      .then((res) => {
        if (cancelled) return;
        setStations(res.stations);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message ?? "Failed to load stations");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useSSE(SSE_URL, {
    status_changed: (d: StatusChangedEvent) => {
      setStations((prev) =>
        prev.map((s) =>
          s.station_id === d.station_id ? { ...s, status: d.status } : s,
        ),
      );
    },
    // Required so the "Last heartbeat" column stays live without polling.
    heartbeat: (d: HeartbeatEvent) => {
      setStations((prev) =>
        prev.map((s) =>
          s.station_id === d.station_id
            ? { ...s, last_heartbeat: d.ts }
            : s,
        ),
      );
    },
    // Feeds the dashboard Power column via active_session.power_kw.
    meter: (d: MeterEvent) => {
      setStations((prev) =>
        prev.map((s) => {
          if (s.station_id !== d.station_id || !s.active_session) return s;
          return {
            ...s,
            active_session: {
              ...s.active_session,
              power_kw: d.power_kw,
              energy_wh: d.energy_wh,
            },
          };
        }),
      );
    },
    session_started: () => refetch(),
    session_ended: () => refetch(),
  });

  return { stations, loading, error };
}
