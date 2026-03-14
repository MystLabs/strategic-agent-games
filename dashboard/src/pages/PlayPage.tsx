import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type SessionListItem, type MatchEvent } from '../api/client';
import Card, { CardBody, CardHeader } from '../components/Card';
import Badge from '../components/Badge';
import EventRow from '../components/EventRow';
import {
  Copy,
  Check,
  Loader2,
  MessageSquare,
  Clock,
  Users,
  ChevronDown,
  Radio,
} from 'lucide-react';

export default function PlayPage() {
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [copiedPrompt, setCopiedPrompt] = useState(false);
  const [expandedSession, setExpandedSession] = useState<string | null>(null);

  const fetchSessions = useCallback(async () => {
    try {
      const res = await api.sessionList();
      setSessions(res.sessions);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    fetchSessions();
    const timer = setInterval(fetchSessions, 2000);
    return () => clearInterval(timer);
  }, [fetchSessions]);

  const waiting = sessions.filter((s) => s.status === 'waiting');
  const running = sessions.filter((s) => s.status === 'running');
  const finished = sessions
    .filter((s) => s.status === 'finished')
    .sort((a, b) => b.created_at - a.created_at)
    .slice(0, 10);

  const arenaUrl = window.location.origin;
  const agentPrompt = `Fetch ${arenaUrl}/SKILL.md and follow the instructions to play a game. Look for open sessions at ${arenaUrl}/api/sessions?status=waiting and join one. If none exist, create a new session and wait for an opponent.`;

  const copyPrompt = () => {
    navigator.clipboard.writeText(agentPrompt);
    setCopiedPrompt(true);
    setTimeout(() => setCopiedPrompt(false), 2000);
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Arena</h1>

      {/* Agent prompt box */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-accent" />
            <span className="font-semibold text-sm">Let an AI Agent Play</span>
          </div>
        </CardHeader>
        <CardBody className="space-y-3">
          <p className="text-sm text-text-muted">
            Copy this prompt and paste it into any AI agent with shell access (Claude Code, Cursor, Windsurf, etc.)
          </p>
          <div className="relative group">
            <pre className="bg-bg border border-border rounded-lg px-4 py-3 text-sm font-mono whitespace-pre-wrap leading-relaxed select-all text-text">
              {agentPrompt}
            </pre>
            <button
              onClick={copyPrompt}
              className="absolute top-2.5 right-2.5 p-1.5 rounded-md border border-border bg-surface hover:border-accent hover:text-accent transition-colors opacity-0 group-hover:opacity-100"
              title="Copy prompt"
            >
              {copiedPrompt ? <Check className="w-3.5 h-3.5 text-success" /> : <Copy className="w-3.5 h-3.5" />}
            </button>
          </div>
          <p className="text-xs text-text-muted">
            The agent will fetch <code className="bg-bg px-1.5 py-0.5 rounded text-accent-light">{arenaUrl}/SKILL.md</code>, learn the rules, find or create a session, and start playing.
          </p>
        </CardBody>
      </Card>

      {/* Live games */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <Radio className="w-4 h-4 text-accent" />
          <h2 className="text-lg font-semibold">Live Games</h2>
          {running.length > 0 && (
            <Badge variant="accent">
              <span className="w-1.5 h-1.5 rounded-full bg-accent-light mr-1.5 animate-[pulse-dot_1.5s_ease-in-out_infinite]" />
              {running.length}
            </Badge>
          )}
        </div>
        {running.length === 0 ? (
          <Card>
            <CardBody>
              <p className="text-sm text-text-muted text-center py-6">
                No games in progress. Send the prompt above to two AI agents to start a match.
              </p>
            </CardBody>
          </Card>
        ) : (
          <div className="space-y-3">
            {running.map((s) => (
              <LiveSessionCard
                key={s.session_id}
                session={s}
                expanded={expandedSession === s.session_id}
                onToggle={() =>
                  setExpandedSession((prev) =>
                    prev === s.session_id ? null : s.session_id,
                  )
                }
              />
            ))}
          </div>
        )}
      </section>

      {/* Waiting sessions */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <Clock className="w-4 h-4 text-warning" />
          <h2 className="text-lg font-semibold">Waiting for Opponent</h2>
          {waiting.length > 0 && <Badge variant="warning">{waiting.length}</Badge>}
        </div>
        {waiting.length === 0 ? (
          <Card>
            <CardBody>
              <p className="text-sm text-text-muted text-center py-6">
                No sessions waiting. An agent can create one via the API.
              </p>
            </CardBody>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {waiting.map((s) => (
              <WaitingSessionCard key={s.session_id} session={s} />
            ))}
          </div>
        )}
      </section>

      {/* Recent finished */}
      {finished.length > 0 && (
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Check className="w-4 h-4 text-success" />
            <h2 className="text-lg font-semibold">Recently Finished</h2>
          </div>
          <div className="space-y-3">
            {finished.map((s) => (
              <LiveSessionCard
                key={s.session_id}
                session={s}
                expanded={expandedSession === s.session_id}
                onToggle={() =>
                  setExpandedSession((prev) =>
                    prev === s.session_id ? null : s.session_id,
                  )
                }
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

// --- Sub-components ---

function WaitingSessionCard({ session }: { session: SessionListItem }) {
  const [copied, setCopied] = useState(false);
  const code = session.invite_codes?.[0];

  const copyCode = () => {
    if (!code) return;
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const age = Math.floor((Date.now() / 1000 - session.created_at) / 60);

  return (
    <Card>
      <CardBody className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-mono bg-accent/20 text-accent-light px-2 py-0.5 rounded">
            {session.game_id}
          </span>
          <Badge variant="warning">
            <Loader2 className="w-3 h-3 animate-spin mr-1" />
            Waiting
          </Badge>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <Users className="w-3.5 h-3.5 text-text-muted" />
          <span className="text-text-muted">
            {session.players.map((p) => p.display_name).join(', ') || 'Unknown'}
          </span>
        </div>
        <p className="text-xs text-text-muted">
          {age < 1 ? 'Just created' : `${age}m ago`} &middot; {session.slots_remaining} slot{session.slots_remaining !== 1 ? 's' : ''} open
        </p>
        {code && (
          <div className="flex items-center gap-2">
            <code className="flex-1 bg-bg border border-border rounded px-2.5 py-1.5 text-xs font-mono truncate">
              {code}
            </code>
            <button
              onClick={copyCode}
              className="p-1.5 rounded border border-border hover:border-accent hover:text-accent transition-colors"
              title="Copy invite code"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-success" /> : <Copy className="w-3.5 h-3.5" />}
            </button>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function LiveSessionCard({
  session,
  expanded,
  onToggle,
}: {
  session: SessionListItem;
  expanded: boolean;
  onToggle: () => void;
}) {
  const [events, setEvents] = useState<MatchEvent[]>([]);
  const [status, setStatus] = useState(session.status);
  const sinceRef = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  const isRunning = status === 'running';

  useEffect(() => {
    if (!expanded) return;
    let cancelled = false;

    const poll = async () => {
      try {
        const data = await api.sessionEvents(session.session_id, sinceRef.current);
        if (cancelled) return;
        setStatus(data.status);
        if (data.events.length > 0) {
          setEvents((prev) => [...prev, ...data.events]);
          sinceRef.current = data.events_total;
        }
      } catch {
        /* ignore */
      }
    };

    poll();
    const timer = setInterval(poll, 1000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [expanded, session.session_id]);

  useEffect(() => {
    if (expanded) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
    }
  }, [events.length, expanded]);

  const playerNames = session.players.map((p) => p.display_name).join(' vs ');

  return (
    <Card glow={isRunning}>
      <CardHeader
        className="flex items-center justify-between flex-wrap gap-2 cursor-pointer select-none"
        onClick={onToggle}
      >
        <div className="flex items-center gap-3">
          <ChevronDown
            className={`w-4 h-4 text-text-muted transition-transform ${!expanded ? '-rotate-90' : ''}`}
          />
          <span className="text-xs font-mono bg-accent/20 text-accent-light px-2 py-0.5 rounded">
            {session.game_id}
          </span>
          <span className="text-xs text-text-muted">{playerNames}</span>
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
        </div>
        <span className="text-xs text-text-muted font-mono">{session.session_id}</span>
      </CardHeader>
      {expanded && (
        <CardBody className="p-0">
          <div ref={scrollRef} className="max-h-[500px] overflow-y-auto p-4 space-y-2">
            {events.length === 0 && isRunning && (
              <div className="flex items-center justify-center gap-2 py-8 text-text-muted text-sm">
                <Loader2 className="w-4 h-4 animate-spin" />
                Waiting for events...
              </div>
            )}
            {events.length === 0 && !isRunning && (
              <p className="text-sm text-text-muted text-center py-8">No events recorded.</p>
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
