import { useCallback, useEffect, useState } from 'react';
import { api, type AgentInfo } from '../api/client';
import Card, { CardBody, CardHeader } from '../components/Card';
import Badge from '../components/Badge';
import { useToast } from '../components/Toast';
import { Plus, Trash2, Globe, X } from 'lucide-react';

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [showForm, setShowForm] = useState(false);
  const { toast } = useToast();

  const refresh = useCallback(() => {
    api.agents().then((a) => setAgents(a.agents)).catch(() => toast('Failed to load agents'));
  }, [toast]);

  useEffect(refresh, [refresh]);

  const handleRemove = async (id: string) => {
    try {
      await api.unregister(id);
      refresh();
    } catch {
      toast('Failed to remove agent');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Agents</h1>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-2 bg-accent hover:bg-accent/80 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" />
          Register Agent
        </button>
      </div>

      {showForm && <RegisterForm onDone={() => { setShowForm(false); refresh(); }} onCancel={() => setShowForm(false)} />}

      {agents.length === 0 ? (
        <Card>
          <CardBody className="text-center py-12 text-text-muted text-sm">
            No agents registered yet. Click "Register Agent" to add one.
          </CardBody>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {agents.map((a) => (
            <Card key={a.agent_id}>
              <CardBody className="space-y-3">
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="font-semibold text-sm">{a.display_name}</h3>
                    <p className="text-xs text-text-muted font-mono mt-0.5">{a.agent_id}</p>
                  </div>
                  <button
                    onClick={() => handleRemove(a.agent_id)}
                    className="p-1.5 rounded-md text-text-muted hover:text-danger hover:bg-danger/10 transition-colors"
                    title="Remove agent"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
                <div className="flex items-center gap-2 text-xs text-text-muted">
                  <Globe className="w-3.5 h-3.5" />
                  <span className="font-mono truncate">{a.endpoint || 'No endpoint'}</span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {a.supported_games?.map((g) => (
                    <Badge key={g}>{g}</Badge>
                  ))}
                </div>
              </CardBody>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function RegisterForm({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [agentId, setAgentId] = useState('');
  const [endpoint, setEndpoint] = useState('http://');
  const [displayName, setDisplayName] = useState('');
  const [games, setGames] = useState('ultimatum,bilateral-trade,first-price-auction,provision-point');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agentId || !endpoint) { setError('Agent ID and endpoint are required'); return; }
    setSubmitting(true);
    setError(null);
    try {
      await api.register(agentId, endpoint, displayName || agentId, games.split(',').map((s) => s.trim()).filter(Boolean));
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card glow>
      <CardHeader className="flex items-center justify-between">
        <span className="font-semibold text-sm">Register New Agent</span>
        <button onClick={onCancel} className="p-1 text-text-muted hover:text-text"><X className="w-4 h-4" /></button>
      </CardHeader>
      <CardBody>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field label="Agent ID" value={agentId} onChange={setAgentId} placeholder="my-agent" />
            <Field label="Display Name" value={displayName} onChange={setDisplayName} placeholder="My Agent" />
          </div>
          <Field label="Endpoint URL" value={endpoint} onChange={setEndpoint} placeholder="http://localhost:5001" />
          <Field label="Supported Games (comma-separated)" value={games} onChange={setGames} />
          {error && <p className="text-sm text-danger">{error}</p>}
          <button
            type="submit"
            disabled={submitting}
            className="bg-accent hover:bg-accent/80 disabled:opacity-40 text-white text-sm font-medium px-6 py-2 rounded-lg transition-colors"
          >
            {submitting ? 'Registering...' : 'Register'}
          </button>
        </form>
      </CardBody>
    </Card>
  );
}

function Field({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div>
      <label className="block text-xs text-text-muted mb-1.5 uppercase tracking-wider">{label}</label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent placeholder:text-text-muted/50"
      />
    </div>
  );
}
