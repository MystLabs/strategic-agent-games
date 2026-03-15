import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type MatchEvent } from '../api/client';
import Badge from './Badge';
import Card, { CardBody, CardHeader } from './Card';
import EventRow from './EventRow';
import { Loader2, ChevronDown } from 'lucide-react';

interface Props {
  sessionId: string;
  gameId?: string;
  agentIds?: string[];
  defaultCollapsed?: boolean;
  onFinished?: () => void;
}

export default function LiveMatch({ sessionId, gameId, agentIds, defaultCollapsed = false, onFinished }: Props) {
  const [events, setEvents] = useState<MatchEvent[]>([]);
  const [status, setStatus] = useState<string>('running');
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const sinceRef = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const wasRunningRef = useRef(true);

  const poll = useCallback(async () => {
    try {
      const data = await api.matchStatus(sessionId, sinceRef.current);
      setStatus(data.status);
      if (data.events && data.events.length > 0) {
        setEvents((prev) => [...prev, ...data.events]);
        sinceRef.current = data.events_total;
      }
      if (data.status !== 'running') {
        if (wasRunningRef.current) {
          wasRunningRef.current = false;
          onFinished?.();
        }
      }
    } catch {
      /* ignore polling errors */
    }
  }, [sessionId, onFinished]);

  useEffect(() => {
    const timer = setInterval(poll, 800);
    poll();
    return () => clearInterval(timer);
  }, [poll]);

  useEffect(() => {
    if (!collapsed) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
    }
  }, [events.length, collapsed]);

  const isRunning = status === 'running';

  const messageCount = events.filter((e) => e.event_type === 'message').length;
  const actionCount = events.filter((e) => e.event_type === 'action').length;

  return (
    <Card glow={isRunning}>
      <CardHeader
        className="flex items-center justify-between flex-wrap gap-2 cursor-pointer select-none"
        onClick={() => setCollapsed((c) => !c)}
      >
        <div className="flex items-center gap-2 sm:gap-3 min-w-0 flex-wrap">
          <ChevronDown
            className={`w-4 h-4 text-text-muted transition-transform flex-shrink-0 ${collapsed ? '-rotate-90' : ''}`}
          />
          {gameId && (
            <span className="text-xs font-mono bg-accent/20 text-accent-light px-2 py-0.5 rounded flex-shrink-0">
              {gameId}
            </span>
          )}
          {agentIds && (
            <span className="text-xs text-text-muted truncate max-w-[120px] sm:max-w-none">
              {agentIds.join(' vs ')}
            </span>
          )}
          {isRunning ? (
            <Badge variant="accent">
              <span className="w-1.5 h-1.5 rounded-full bg-accent-light mr-1.5 animate-[pulse-dot_1.5s_ease-in-out_infinite]" />
              Live
            </Badge>
          ) : (
            <Badge variant={status === 'finished' ? 'success' : 'danger'}>
              {status === 'finished' ? 'Finished' : 'Error'}
            </Badge>
          )}
          {collapsed && (
            <span className="text-[11px] text-text-muted">
              {messageCount} msg · {actionCount} actions
            </span>
          )}
        </div>
        <span className="text-xs text-text-muted font-mono truncate max-w-[100px] sm:max-w-none" title={sessionId}>{sessionId}</span>
      </CardHeader>
      {!collapsed && (
        <CardBody className="p-0">
          <div ref={scrollRef} className="max-h-[400px] sm:max-h-[500px] overflow-y-auto p-3 sm:p-4 space-y-2">
            {events.length === 0 && isRunning && (
              <div className="flex items-center justify-center gap-2 py-8 text-text-muted text-sm">
                <Loader2 className="w-4 h-4 animate-spin" />
                Waiting for events...
              </div>
            )}
            {events.map((ev, i) => (
              <EventRow key={i} event={ev} />
            ))}
          </div>
        </CardBody>
      )}
    </Card>
  );
}
