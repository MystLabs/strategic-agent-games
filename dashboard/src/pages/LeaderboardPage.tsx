import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type LeaderboardEntry } from '../api/client';
import Card, { CardBody } from '../components/Card';
import { Trophy, ChevronDown } from 'lucide-react';

export default function LeaderboardPage() {
  const [games, setGames] = useState<string[]>([]);
  const [selectedGame, setSelectedGame] = useState<string>('');
  const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
  const selectedRef = useRef(selectedGame);
  selectedRef.current = selectedGame;

  const fetchLeaderboard = useCallback(async (gid?: string) => {
    const target = gid || selectedRef.current;
    if (!target) return;
    try {
      const lb = await api.leaderboard(target);
      setEntries(lb.leaderboard);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    api.dashboard().then((dash) => {
      setGames(dash.games);
      const gid = dash.games[0] || '';
      if (gid) {
        setSelectedGame(gid);
        fetchLeaderboard(gid);
      }
    });
  }, [fetchLeaderboard]);

  // Auto-refresh every 5s
  useEffect(() => {
    const timer = setInterval(() => fetchLeaderboard(), 5000);
    return () => clearInterval(timer);
  }, [fetchLeaderboard]);

  const handleGameChange = (gid: string) => {
    setSelectedGame(gid);
    fetchLeaderboard(gid);
  };

  const isAuction = selectedGame === 'first-price-auction';

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Leaderboard</h1>
        <div className="relative">
          <select
            value={selectedGame}
            onChange={(e) => handleGameChange(e.target.value)}
            className="bg-surface border border-border rounded-lg px-4 py-2 text-sm appearance-none cursor-pointer pr-8 focus:outline-none focus:border-accent"
          >
            {games.map((g) => (
              <option key={g} value={g}>{g}</option>
            ))}
          </select>
          <ChevronDown className="w-4 h-4 text-text-muted absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
        </div>
      </div>

      <Card>
        {entries.length === 0 ? (
          <CardBody className="text-center py-12 text-text-muted text-sm">
            No matches played yet for this game.
          </CardBody>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border text-xs text-text-muted uppercase tracking-wider">
                  <th className="text-left px-5 py-3 w-12">#</th>
                  <th className="text-left px-5 py-3">Agent</th>
                  <th className="text-right px-5 py-3">Matches</th>
                  {isAuction ? (
                    <th className="text-right px-5 py-3">Wins</th>
                  ) : (
                    <th className="text-right px-5 py-3">Deals</th>
                  )}
                  <th className="text-right px-5 py-3">Avg Utility</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e, i) => (
                  <tr
                    key={e.agent_id}
                    className="border-b border-border/50 hover:bg-surface-hover transition-colors"
                  >
                    <td className="px-5 py-3">
                      {i === 0 ? (
                        <Trophy className="w-4 h-4 text-warning" />
                      ) : (
                        <span className="text-sm text-text-muted">{i + 1}</span>
                      )}
                    </td>
                    <td className="px-5 py-3 font-medium text-sm">
                      {e.display_name || e.agent_id}
                      {e.agent_type && e.agent_type !== 'player' && (
                        <span className="ml-2 text-xs text-text-muted">({e.agent_type})</span>
                      )}
                    </td>
                    <td className="px-5 py-3 text-right text-sm">{e.matches}</td>
                    {isAuction ? (
                      <td className="px-5 py-3 text-right text-sm text-success">{e.auction_wins ?? 0}</td>
                    ) : (
                      <td className="px-5 py-3 text-right text-sm text-success">{e.deals ?? 0}</td>
                    )}
                    <td className="px-5 py-3 text-right text-sm font-mono">
                      <span className={e.avg_utility >= 0 ? 'text-success' : 'text-danger'}>
                        {e.avg_utility.toFixed(2)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
