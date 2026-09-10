import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchBackgroundJob,
  isTerminal,
  type BackgroundJob,
} from "@/api/backgroundJobs";

export function useBackgroundJob(onDone?: (job: BackgroundJob) => void) {
  const [job, setJob] = useState<BackgroundJob | null>(null);
  const [tracking, setTracking] = useState(false);
  const timer = useRef<number | null>(null);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  const stop = useCallback(() => {
    if (timer.current !== null) {
      window.clearInterval(timer.current);
      timer.current = null;
    }
    setTracking(false);
  }, []);

  const track = useCallback(
    (id: string, intervalMs = 1500) => {
      stop();
      setTracking(true);
      const tick = async () => {
        try {
          const current = await fetchBackgroundJob(id);
          setJob(current);
          if (isTerminal(current)) {
            stop();
            doneRef.current?.(current);
          }
        } catch {
          /* transient polling error — retry on next tick */
        }
      };
      void tick();
      timer.current = window.setInterval(() => void tick(), intervalMs);
    },
    [stop],
  );

  const reset = useCallback(() => {
    stop();
    setJob(null);
  }, [stop]);

  useEffect(() => stop, [stop]);

  return { job, tracking, track, stop, reset };
}
