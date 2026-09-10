import { useState, useEffect } from 'react';

/**
 * Returns whether a CSS media query currently matches.
 * Re-evaluates on resize / orientation change.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window !== 'undefined') {
      return window.matchMedia(query).matches;
    }
    return false;
  });

  useEffect(() => {
    const mql = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);

    setMatches(mql.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, [query]);

  return matches;
}

/** True when viewport height <= 720px — the sidebar drops to the compact
 * density and hides the footer project block so the nav list stays fully
 * visible. */
export function useIsShortViewport(): boolean {
  return useMediaQuery('(max-height: 720px)');
}
