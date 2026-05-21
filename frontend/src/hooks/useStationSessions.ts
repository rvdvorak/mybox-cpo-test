// Sessions history data hook (architektura 8.6).
// Paginated GET /api/stations/:id/sessions with a "Load more" accumulator.

import { useCallback, useEffect, useState } from "react";
import { getSessions } from "../api/apiClient";
import type { Session } from "../types";

const PAGE_SIZE = 50;

export function useStationSessions(stationId: string) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Initial page.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setSessions([]);
    getSessions(stationId, PAGE_SIZE, 0)
      .then((res) => {
        if (cancelled) return;
        setSessions(res.sessions);
        setTotal(res.total);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message ?? "Failed to load sessions");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [stationId]);

  const loadMore = useCallback(() => {
    setLoadingMore(true);
    getSessions(stationId, PAGE_SIZE, sessions.length)
      .then((res) => {
        setSessions((prev) => [...prev, ...res.sessions]);
        setTotal(res.total);
        setError(null);
      })
      .catch((e) => setError(e.message ?? "Failed to load more sessions"))
      .finally(() => setLoadingMore(false));
  }, [stationId, sessions.length]);

  const hasMore = sessions.length < total;

  return { sessions, total, loading, loadingMore, error, hasMore, loadMore };
}
