# Changelog

## Session 1 — Initial Creation

Original files created by prior session (before this agent's involvement):
- `server.py` — Basic FastAPI server with 4 hardcoded agents, WebSocket debate loop, Ollama streaming
- `index.html` — Dark-themed UI with agent cards, round tabs, topic chips
- `start.sh` — Startup script checking Ollama, installing deps, launching server
- `README.md` — Setup instructions and agent table

## Session 2 — Phase 1 + Phase 2 Implementation (March 8, 2026)

### Phase 1: Dynamic Agents + Model Discovery

**server.py changes:**
- Removed hardcoded AGENTS list from runtime
- Added `agents.json` file persistence (load on startup, save on every change)
- Added `DEFAULT_AGENTS` as fallback for first-run
- Added `GET /api/models` — queries Ollama for all installed models
- Added `GET /api/agents` — returns full agent config
- Added `POST /api/agents` — bulk-save agents (from UI modal)
- Added `POST /api/agents/new` — create single agent
- Added `PUT /api/agents/{agent_id}` — update agent fields
- Added `DELETE /api/agents/{agent_id}` — remove agent
- Added Pydantic models: `AgentUpdate`, `AgentCreate`
- Removed old `GET /agents` endpoint (replaced by `/api/agents`)

**index.html changes:**
- Removed hardcoded `AGENTS` JavaScript array
- Added `init()` function that fetches agents from `/api/agents` on page load
- Added `loadModels()` function that fetches from `/api/models`
- Added Agent Manager modal (overlay + modal component)
- Modal features: agent list with edit/delete, expandable fields, color picker, model dropdown, persona textarea, add new agent button, save button
- Arena grid now uses dynamic column classes based on agent count
- Agent card colors driven by CSS custom properties (not hardcoded per-agent CSS)

### Phase 2: Live Debate Controls

**server.py changes:**
- Added `cancel_event`, `pause_event`, `skip_event` (asyncio.Event) to debate WebSocket handler
- Added `listen_for_controls()` background task — receives pause/resume/stop/skip during debate
- Modified `stream_ollama()` to accept `cancel_event` — breaks HTTP stream immediately on cancel
- Added pause checks between agents and between rounds
- Server sends `debate_paused`, `debate_resumed`, `debate_stopped` events
- `agent_done` event now includes `skipped` boolean
- Server sends `agents_config` message at debate start so frontend knows exact agents for this debate

**index.html changes:**
- Added Live Controls Bar (hidden by default, shown during debate)
- Buttons: Pause/Resume (toggles), Skip Agent, Stop
- Pause button changes to "Resume" with green styling when paused
- Stop triggers "Debate Stopped" red banner
- Added `debateAction()` function to send control messages via WebSocket
- Added keyboard shortcuts: Space (pause/resume), Escape (stop), N (skip)
- Added PAUSED status dot state (gold pulsing)
- Frontend now uses `agents_config` message from server to build arena (not local AGENTS)

### Bug Fixes

- **WebSocket 404 error**: Added `websockets` to pip install in `start.sh`
- **Think tags visible during streaming**: Added server-side state machine in `stream_ollama()` to filter `<think>...</think>` blocks before they reach the WebSocket

### New Agents Added

- **The Tactician** (mistral:7b) — action-focused, demands concrete steps
- **The Wildcard** (llama3.2:3b) — lateral thinker, unexpected connections

### Files Created
- `agents.json` — 6 agents with 4 different models
- `progress/SYSTEM_CONTEXT.md` — Full system briefing for future AI agents
- `progress/CHANGELOG.md` — This file

## Session 3 — Bug Fixes + Synthesis Panel + Quick Persona Edit (March 8, 2026)

### Critical Bug Fix: Blank Agent Output

**Root cause:** `num_predict: 300` was too small for DeepSeek R1 / r1-wild models. These models always open with a `<think>...</think>` block that consumes 200-400+ tokens. When the token budget ran out while still inside the think block, the server-side filter's end-of-stream guard (`if think_buffer and not inside_think`) never fired, so zero tokens were emitted to the browser. Cards stayed on "Waiting..." for the entire response.

**Fix in `server.py`:**
- `num_predict`: 300 → 2500
- `temperature`: 0.85 → 1.0
- Added `num_ctx`: 8192 (optimized for M1 16GB)

### Response Depth Fix

**`server.py` DEFAULT_AGENTS + `agents.json`:**
- All 6 agent personas updated from "Keep responses to 3-4 sharp sentences" to "Give a substantive response of 5-8 sentences" with per-agent domain-specific depth instructions
- Each agent's core character/personality is unchanged

### Grand Debate Synthesis Panel

**`index.html` additions:**
- `renderSynthesis()` function builds a full chronological transcript of the debate
- Called automatically from the `debate_complete` WebSocket handler
- Panel auto-scrolls into view after debate ends
- Each round has a SOLO/DEBATE mode badge divider
- Each agent entry has a colored left border matching their `agent.color`
- Panel is collapsible (click header to toggle)
- `toggleSynthesis()` handles expand/collapse

### Quick Persona Edit Popover

**`index.html` additions:**
- Pencil icon (✎) added to every agent card header (visible on card hover via CSS opacity)
- `openPersonaEdit(agentId, btnEl)` positions a fixed popover near the clicked button
- Popover contains: agent emoji/name (colored), persona textarea, Save and Cancel buttons
- `savePersonaEdit()` calls `PUT /api/agents/{id}` and updates in-memory `AGENTS` array
- `closePersonaEdit()` and click-outside handler close the popover
- Escape key now closes the popover first (before stopping debate)
- Edit is blocked during an active debate
