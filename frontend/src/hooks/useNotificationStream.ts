import { useCallback, useEffect, useRef, useState } from "react";
import { streamNotifications } from "@/api/notificationStream";
import { fetchUnreadCount } from "@/api/engagement";

export interface NotificationStreamState {
  unreadCount: number;
  /** Latest live event (toast-preview material), consumed once. */
  lastEvent: Record<string, unknown> | null;
  connected: boolean;
  refresh: () => Promise<void>;
}

/** Live unread badge + toast previews over the plan-36 SSE stream;
 * REST stays the source of truth and reconnects with last-event-id. */
export function useNotificationStream(): NotificationStreamState {
  const [unreadCount, setUnreadCount] = useState(0);
  const [lastEvent, setLastEvent] = useState<Record<string, unknown> | null>(
    null,
  );
  const [connected, setConnected] = useState(false);
  const refreshRef = useRef<() => Promise<void>>(async () => {});

  const refresh = useCallback(async () => {
    try {
      const { unread_count } = await fetchUnreadCount();
      setUnreadCount(unread_count);
    } catch {
      setUnreadCount(0);
    }
  }, []);

  refreshRef.current = refresh;

  useEffect(() => {
    const controller = new AbortController();
    void refreshRef.current();
    void streamNotifications(
      (event) => {
        setConnected(true);
        if (event.event === "unread") {
          setUnreadCount(event.data.unread_count);
        } else {
          setLastEvent(event.data);
          void refreshRef.current();
        }
      },
      controller.signal,
    ).finally(() => setConnected(false));
    return () => controller.abort();
  }, []);

  return { unreadCount, lastEvent, connected, refresh };
}
