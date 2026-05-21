// Station detail data hook (architektura 8.6).
// Holds the station detail plus a meter-readings buffer for the chart,
// combining the initial GET with live SSE updates.

import { useCallback, useEffect, useState } from "react";
import { getStation, SSE_URL } from "../api/apiClient";
import type {
  MeterEvent,
  MeterReading,
  SessionEndedEvent,
  SessionStartedEvent,
  StationDetail,
  StatusChangedEvent,
} from "../types";
import { useSSE } from "./useSSE";

// Keep ~5 minutes of readings at a 5s tick (architektura 7.2 / 8.4).
const MAX_READINGS = 60;

export function useStationDetail(stationId: string) {
  const [detail, setDetail] = useState<StationDetail | null>(null);
  const [meterReadings, setMeterReadings] = useState<MeterReading[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Initial load (re-runs when the route param changes).
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setDetail(null);
    getStation(stationId)
      .then((d) => {
        if (cancelled) return;
        setDetail(d);
        // recent_meter_readings arrive ascending — do not re-sort.
        setMeterReadings(d.recent_meter_readings);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message ?? "Failed to load station");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [stationId]);

  // Re-fetch on session boundaries to refresh active_session + readings.
  const refetch = useCallback(() => {
    getStation(stationId)
      .then((d) => {
        setDetail(d);
        setMeterReadings(d.recent_meter_readings);
        setError(null);
      })
      .catch((e) => setError(e.message ?? "Failed to refresh station"));
  }, [stationId]);

  useSSE(SSE_URL, {
    status_changed: (d: StatusChangedEvent) => {
      if (d.station_id !== stationId) return;
      setDetail((prev) => (prev ? { ...prev, status: d.status } : prev));
    },
    meter: (d: MeterEvent) => {
      if (d.station_id !== stationId) return;
      setMeterReadings((prev) => {
        const next = [
          ...prev,
          { ts: d.ts, power_kw: d.power_kw, energy_wh: d.energy_wh },
        ];
        return next.length > MAX_READINGS
          ? next.slice(next.length - MAX_READINGS)
          : next;
      });
      // Keep the active-session panel figures in sync.
      setDetail((prev) => {
        if (!prev || !prev.active_session) return prev;
        return {
          ...prev,
          active_session: {
            ...prev.active_session,
            power_kw: d.power_kw,
            energy_wh: d.energy_wh,
          },
        };
      });
    },
    session_started: (d: SessionStartedEvent) => {
      if (d.station_id === stationId) refetch();
    },
    session_ended: (d: SessionEndedEvent) => {
      if (d.station_id === stationId) refetch();
    },
  });

  return { detail, meterReadings, loading, error };
}
