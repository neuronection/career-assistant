import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";
import { useLocation, useNavigationType } from "react-router-dom";

import { isListReturn } from "@/lib/listReturn";
import { journaledScroll, recordScroll } from "@/lib/scrollJournal";

/** Restores the `#main` scroller across navigations: POP returns to the
 * journaled offset, a fresh PUSH starts at the top, a PUSH that carries the
 * list-return state re-enters the list at its journaled offset, and REPLACE
 * (filter patches, mount canonicalization) never moves the scroll. */
export function useMainScrollRestoration(
  mainRef: RefObject<HTMLElement | null>
): void {
  const location = useLocation();
  const navigationType = useNavigationType();
  const locationRef = useRef(location);
  locationRef.current = location;

  useEffect(() => {
    const el = mainRef.current;
    if (!el) return undefined;
    const onScroll = () => {
      recordScroll(
        `${locationRef.current.pathname}${locationRef.current.search}`,
        el.scrollTop
      );
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [mainRef]);

  useLayoutEffect(() => {
    const el = mainRef.current;
    if (!el || navigationType === "REPLACE") return;
    const key = `${location.pathname}${location.search}`;
    el.scrollTop =
      navigationType === "POP" || isListReturn(location.state)
        ? journaledScroll(key)
        : 0;
  }, [location, navigationType, mainRef]);
}
