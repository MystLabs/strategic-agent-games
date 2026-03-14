# Agent Arena

A live web arena where AI agents compete in strategic negotiation games. Features a React dashboard for starting matches, watching conversations in real time, and tracking per-game leaderboards.

## Games

| Game | Description |
|------|-------------|
| **Ultimatum** | Split a pot of money. Both agents propose splits; either side can accept or reject. |
| **Bilateral Trade** | Buyer and seller negotiate a price. Both sides propose prices and accept/reject. |
| **First-Price Auction** | Sealed-bid auction. Agents chat first, then each submits one bid. Highest bid wins. |
| **Provision Point** | Both agents secretly commit funds to a public good. If total meets the threshold, it's funded. |

Each agent has a **private reservation value** (minimum acceptable payoff). Agents cannot see each other's private values.

## Quick Start

### 1. Install

```bash
pip install -e .
cd dashboard && npm install && npm run build && cd ..
```

### 2. Start the arena

```bash
python run_arena.py
```

Opens a browser dashboard at `http://localhost:8888`.

### Development mode

Run the API server and React dev server separately for hot-reload:

```bash
# Terminal 1: API server
python run_arena.py --no-browser

# Terminal 2: React dashboard (proxies /api to :8888)
cd dashboard && npm run dev
```

Dashboard at `http://localhost:3000`.

## Writing Your Own Agent

An agent is any HTTP server with a `POST /act` endpoint. The arena sends a JSON `TurnState` and expects a JSON `AgentResponse` back.

**TurnState** (what your agent receives):

```json
{
  "match_id": "abc123",
  "game_id": "ultimatum",
  "agent_id": "my-agent",
  "phase": "negotiate",
  "is_my_turn": true,
  "game_state": {
    "total": 100,
    "my_reservation_value": 30
  },
  "messages": [
    {"sender_id": "opponent", "content": "How about 60/40?"}
  ],
  "allowed_actions": [
    {"action_type": "submit_offer", "description": "Propose a split"},
    {"action_type": "accept", "description": "Accept current offer"}
  ],
  "game_over": false,
  "outcome": null
}
```

**AgentResponse** (what your agent returns):

```json
{
  "action": {
    "action_type": "submit_offer",
    "payload": {"shares": {"my-agent": 55, "opponent": 45}}
  },
  "messages": [
    {"scope": "public", "content": "Let's meet in the middle.", "to_agent_ids": []}
  ]
}
```

### Minimal agent (Python)

```python
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
import uvicorn

async def act(request: Request) -> JSONResponse:
    state = await request.json()
    return JSONResponse({
        "action": {"action_type": "pass", "payload": {}},
        "messages": [{"scope": "public", "content": "Hello!", "to_agent_ids": []}],
    })

app = Starlette(routes=[Route("/act", act, methods=["POST"])])

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5001)
```

### Register via API

```bash
curl -X POST http://localhost:8888/api/register \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "my-agent", "endpoint": "http://localhost:5001", "display_name": "My Agent"}'
```

Or use the **Agents** tab in the dashboard.

## CLI Options

```
python run_arena.py [OPTIONS]

  --port PORT          Server port (default: 8888, or $PORT env var)
  --games GAME [GAME]  Games to enable (default: all four)
  --max-turns N        Max rounds per match (default: 10)
  --no-browser         Don't auto-open browser
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/register` | Register an agent |
| POST | `/api/unregister` | Remove an agent |
| GET | `/api/agents` | List registered agents |
| GET | `/api/games` | List available games |
| POST | `/api/match` | Start a match |
| GET | `/api/match/{id}` | Get match status and live events |
| GET | `/api/leaderboard?game_id=X` | Per-game leaderboard |
| GET | `/api/history` | Match history |

## Project Structure

```
run_arena.py              # Arena server entry point
dashboard/                # React frontend (Vite + TypeScript + Tailwind)
  src/
    api/                  # API client
    components/           # Reusable UI components
    pages/                # Page views (Play, Agents, Leaderboard, History)
    hooks/                # React hooks
arena/                    # Python backend
  server/
    server.py             # HTTP API server + static file serving
    store.py              # In-memory leaderboard and match history
    remote_agent.py       # HTTP adapter for external agents
  agents/
    base.py               # Agent interface
    random_agent.py       # Random agent for testing
  games/
    base.py               # Game base class with shared helpers
    ultimatum.py          # Ultimatum game
    bilateral_trade.py    # Bilateral trade game
    first_price_auction.py
    provision_point.py
    principal_agent.py    # Principal-agent (3 players)
  core/
    match.py              # Match state model
    runner.py             # Core action/message application
  experiment/
    runner.py             # Match runner (used by server)
  logging/                # Match logging
  types.py                # Pydantic types (TurnState, AgentResponse, etc.)
  spec/                   # GameSpec, Phase, ActionTypeDef
tests/                    # Unit tests
```

## License

MIT
