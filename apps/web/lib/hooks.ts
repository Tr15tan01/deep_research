"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "./api";
import type { Job, JobEvent } from "./types";
import { TERMINAL } from "./utils";

export interface ApiState<T> {
  data: T | undefined;
  error: ApiError | Error | undefined;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (d: T | undefined) => void;
}

/** Minimal data hook: fetch on mount/key change, keep previous data while revalidating. */
export function useApi<T>(path: string | null, deps: unknown[] = []): ApiState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<ApiError | Error>();
  const [loading, setLoading] = useState<boolean>(!!path);
  const seq = useRef(0);
  const depKey = JSON.stringify(deps);

  const load = useCallback(async () => {
    if (!path) return;
    const mine = ++seq.current;
    setLoading(true);
    try {
      const d = await api<T>(path);
      if (mine === seq.current) {
        setData(d);
        setError(undefined);
      }
    } catch (e) {
      if (mine === seq.current) setError(e as Error);
    } finally {
      if (mine === seq.current) setLoading(false);
    }
    // depKey re-runs the fetch when caller-provided dependencies change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, depKey]);

  useEffect(() => {
    void load();
  }, [load]);

  return { data, error, loading, reload: load, setData };
}

export type ConnectionState = "connecting" | "live" | "reconnecting" | "polling" | "closed" | "offline";

/**
 * Live research events.
 * 1. Loads the full persisted history (so navigating away and back loses nothing).
 * 2. Streams new events over SSE; the browser resumes with Last-Event-ID after drops.
 * 3. After repeated SSE failures, falls back to polling the persisted events.
 */
export function useJobEvents(jobId: string) {
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [job, setJob] = useState<Job>();
  const [conn, setConn] = useState<ConnectionState>("connecting");
  const [loadError, setLoadError] = useState<ApiError | Error>();
  const lastSeq = useRef(0);
  const esRef = useRef<EventSource | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const failures = useRef(0);
  const stopped = useRef(false);

  const merge = useCallback((incoming: JobEvent[]) => {
    if (!incoming.length) return;
    setEvents((prev) => {
      const seen = new Set(prev.map((e) => e.seq));
      const add = incoming.filter((e) => !seen.has(e.seq));
      if (!add.length) return prev;
      const next = [...prev, ...add].sort((a, b) => a.seq - b.seq);
      lastSeq.current = next[next.length - 1]?.seq ?? lastSeq.current;
      return next;
    });
  }, []);

  const refreshJob = useCallback(async () => {
    try {
      const d = await api<{ job: Job }>(`/api/v1/research/${jobId}`);
      setJob(d.job);
      return d.job;
    } catch (e) {
      setLoadError(e as Error);
      return undefined;
    }
  }, [jobId]);

  const stopAll = useCallback((state: ConnectionState) => {
    esRef.current?.close();
    esRef.current = null;
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
    setConn(state);
  }, []);

  const poll = useCallback(async () => {
    try {
      const d = await api<{ events: JobEvent[]; job: Job }>(`/api/v1/research/${jobId}/events?after=${lastSeq.current}`);
      merge(d.events);
      setJob(d.job);
      if (TERMINAL.has(d.job.status)) stopAll("closed");
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) setConn("offline");
    }
  }, [jobId, merge, stopAll]);

  const startPolling = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
    setConn("polling");
    if (!pollRef.current) pollRef.current = setInterval(() => void poll(), 3000);
  }, [poll]);

  const connect = useCallback(() => {
    if (stopped.current || typeof EventSource === "undefined") {
      startPolling();
      return;
    }
    esRef.current?.close();
    const es = new EventSource(`/api/v1/research/${jobId}/stream?after=${lastSeq.current}`);
    esRef.current = es;
    es.onopen = () => {
      failures.current = 0;
      setConn("live");
    };
    es.addEventListener("progress", (ev) => {
      try {
        const e = JSON.parse((ev as MessageEvent).data) as JobEvent;
        merge([e]);
        if (["stage", "status", "report", "completed", "failed", "cancelled", "retry", "plan"].includes(e.type)) void refreshJob();
      } catch {
        /* ignore malformed frame */
      }
    });
    es.addEventListener("status", (ev) => {
      try {
        setJob(JSON.parse((ev as MessageEvent).data) as Job);
      } catch {
        /* ignore */
      }
    });
    es.addEventListener("end", () => {
      stopAll("closed");
      void refreshJob();
    });
    es.onerror = () => {
      failures.current += 1;
      if (failures.current >= 4) {
        startPolling();
      } else {
        setConn("reconnecting");
        // The browser retries automatically and sends Last-Event-ID, so no events are lost.
      }
    };
  }, [jobId, merge, refreshJob, startPolling, stopAll]);

  useEffect(() => {
    stopped.current = false;
    let cancelled = false;
    (async () => {
      try {
        const d = await api<{ events: JobEvent[]; job: Job }>(`/api/v1/research/${jobId}/events?after=0&limit=500`);
        if (cancelled) return;
        merge(d.events);
        setJob(d.job);
        if (TERMINAL.has(d.job.status)) {
          setConn("closed");
          return;
        }
        connect();
      } catch (e) {
        if (!cancelled) setLoadError(e as Error);
      }
    })();
    const onOnline = () => {
      if (!stopped.current && esRef.current === null && !TERMINAL.has(job?.status ?? "")) connect();
    };
    const onOffline = () => setConn("offline");
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      cancelled = true;
      stopped.current = true;
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      esRef.current?.close();
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  // While a run is in progress, re-sync the job every minute. Besides catching anything a stream missed,
  // this is regular inbound traffic, which keeps sleep-on-idle hosts (e.g. free tiers) awake mid-research.
  const running = !!job && !TERMINAL.has(job.status) && job.status !== "awaiting_approval";
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => void refreshJob(), 60_000);
    return () => clearInterval(t);
  }, [running, refreshJob]);

  const reconnect = useCallback(() => {
    failures.current = 0;
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
    stopped.current = false;
    connect();
  }, [connect]);

  return { events, job, setJob, conn, loadError, refreshJob, reconnect };
}

export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}
