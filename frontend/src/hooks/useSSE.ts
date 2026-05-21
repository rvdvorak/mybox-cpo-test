// Generic Server-Sent Events hook (architektura 8.7).
// Opens an EventSource on mount, closes it on unmount, and dispatches each
// named event type to its handler. EventSource auto-reconnects on its own;
// onerror only logs.

import { useEffect, useRef } from "react";

// Map of SSE event type -> handler. Payload is parsed JSON (typed by caller).
export type SSEHandlers = Record<string, (data: any) => void>;

export function useSSE(url: string, handlers: SSEHandlers) {
  // Keep handlers in a ref so a reconnect/re-render does not re-open the
  // connection; the effect depends only on `url`.
  const handlersRef = useRef<SSEHandlers>(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    const source = new EventSource(url);
    const eventTypes = Object.keys(handlersRef.current);
    const listeners: Record<string, (e: MessageEvent) => void> = {};

    for (const type of eventTypes) {
      const listener = (e: MessageEvent) => {
        const handler = handlersRef.current[type];
        if (!handler) return;
        try {
          handler(JSON.parse(e.data));
        } catch (err) {
          console.error(`SSE: failed to parse '${type}' payload`, err);
        }
      };
      listeners[type] = listener;
      source.addEventListener(type, listener);
    }

    source.onerror = () => {
      // Browser EventSource reconnects automatically; just surface it.
      console.warn("SSE connection error — browser will retry");
    };

    return () => {
      for (const type of eventTypes) {
        source.removeEventListener(type, listeners[type]);
      }
      source.close();
    };
  }, [url]);
}
