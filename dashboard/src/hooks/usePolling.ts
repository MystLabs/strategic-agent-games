import { useEffect, useRef, useState } from 'react';

export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  enabled = true,
): { data: T | null; error: Error | null; loading: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    if (!enabled) return;

    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      try {
        const result = await fetcher();
        if (mountedRef.current) {
          setData(result);
          setError(null);
          setLoading(false);
        }
      } catch (e) {
        if (mountedRef.current) {
          setError(e as Error);
          setLoading(false);
        }
      }
      if (mountedRef.current) timer = setTimeout(poll, intervalMs);
    };

    poll();

    return () => {
      mountedRef.current = false;
      clearTimeout(timer);
    };
  }, [fetcher, intervalMs, enabled]);

  return { data, error, loading };
}
