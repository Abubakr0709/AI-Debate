# ARENA — AI Debate System: Full Context for Continuation

> This document is a complete briefing for any AI assistant continuing work on this project. Read this first.

## Project Goal

A **local-only, free** multi-agent AI debate platform. Multiple AI agents (running via Ollama on the user's hardware) debate user-chosen topics in real time. The user watches, controls (pause/stop/skip), and can edit agent roles/personas from the browser UI.

## Architecture

```
Browser (index.html)
    |
    |-- REST API (fetch /api/agents, /api/models, etc.)
    |-- WebSocket (ws://localhost:8765/ws/debate)
    |
FastAPI Server (server.py, port 8765)
    |
    |-- Agents config (agents.json — file-persisted)
    |-- Ollama HTTP API (localhost:11434)
    |
Ollama (local LLM runtime)
    |-- huihui_ai/deepseek-r1-abliterated:8b-llama-distill
    |-- r1-wild:latest
    |-- mistral:7b
    |-- llama3.2:3b
```

**Single-page app**: `index.html` is served by FastAPI. No build step, no npm, no frameworks. Pure vanilla JS + CSS.

## File Structure

```
AI Debate/
├── server.py          # FastAPI backend (all logic)
├── index.html         # Full frontend (HTML + CSS + JS in one file)
├── agents.json        # Agent configurations (auto-created, editable via UI)
├── start.sh           # Startup script (checks Ollama, installs deps, runs server)
├── README.md          # User-facing readme
└── progress/
    └── SYSTEM_CONTEXT.md   # This file
```

## What Has Been Implemented

### Phase 1: Dynamic Agents + Model Discovery (DONE)

**Backend (server.py):**
- `GET /api/models` — Queries Ollama `/api/tags`, returns all installed models with name, size, parameter_size, family, quantization
- `GET /api/agents` — Returns current agent list from memory (loaded from agents.json)
- `POST /api/agents` — Bulk-save entire agents list (from the Agent Manager UI)
- `POST /api/agents/new` — Create a single new agent (auto-generates ID)
- `PUT /api/agents/{agent_id}` — Update individual agent fields
- `DELETE /api/agents/{agent_id}` — Remove an agent
- `agents.json` — Auto-created on first run with defaults; persisted on every change
- Supports 1-8+ agents dynamically

**Frontend (index.html):**
- Agents fetched from `/api/agents` on page load (no hardcoded JS array)
- "Manage Agents" button in header opens modal
- Modal: list of agents with edit/delete, expandable fields (name, emoji, color picker, model dropdown, persona textarea)
- "+ Add New Agent" button at bottom
- Model dropdown populated from `/api/models` (shows model name + parameter size)
- "Save Changes" POSTs to `/api/agents`
- Arena grid adapts: 2 cols (1-4 agents), 3 cols (5-6), 4 cols (7-8)
- Agent card colors are dynamic (CSS custom properties from agent.color)

### Phase 2: Live Debate Controls (DONE)

**Backend (server.py):**
- Bidirectional WebSocket: server runs a listener task during debates that accepts control messages
- `{"action": "pause"}` — Pauses after current token; sends `debate_paused`
- `{"action": "resume"}` — Resumes; sends `debate_resumed`
- `{"action": "stop"}` — Cancels generation, ends debate; sends `debate_stopped`
- `{"action": "skip"}` — Cancels current agent, moves to next; marks `[Skipped]`
- `cancel_event` (asyncio.Event) passed to `stream_ollama()` — breaks HTTP stream immediately on skip/stop
- `pause_event` — checked between agents and rounds, tight 200ms poll loop
- Server-side `<think>` tag filtering: DeepSeek R1 thinking blocks are stripped during streaming (not after)

**Frontend (index.html):**
- Live Controls Bar appears during active debate: Pause/Resume, Skip Agent, Stop
- Pause toggles to Resume (changes style to green)
- Stop shows red "Debate Stopped" banner
- Complete shows green "Debate Complete" banner
- Status states: IDLE (gray), LIVE (green pulse), PAUSED (gold pulse), STOPPED (gray), COMPLETE (gold)
- Current agent name shown in control bar
- Keyboard shortcuts (disabled when typing in inputs):
  - Space = pause/resume
  - Escape = stop
  - N = skip agent

### Bug Fixes Applied

- **WebSocket 404**: `websockets` Python package was missing. Added to `start.sh` deps.
- **Think tags visible during stream**: Moved filtering from client-side post-processing to server-side streaming with a state machine.
- **Blank agent output (critical)**: `num_predict: 300` was too low -- DeepSeek R1 think blocks consume 200-400+ tokens, exhausting the budget before any real output. When the token limit was hit inside `<think>`, the end-of-stream guard (`if think_buffer and not inside_think`) never fired, so zero tokens reached the browser. Fixed by raising `num_predict` to 2500 and adding `num_ctx: 8192`.
- **Responses too short**: Personas instructed "3-4 sentences" which capped visible output. Updated all 6 personas to request 5-8 sentences with domain-specific depth instructions.

## Current Agents (6 total, 4 models)

| Agent | Model | Role |
|---|---|---|
| The Analyst | deepseek-r1-abliterated:8b | Data-driven, quantitative, skeptical |
| The Strategist | r1-wild:latest | Big-picture, systems thinker, bold |
| Devil's Advocate | deepseek-r1-abliterated:8b | Destroys weak arguments, provocative |
| The Synthesizer | r1-wild:latest | Finds signal from noise, distills clarity |
| The Tactician | mistral:7b | Action-focused, demands concrete steps |
| The Wildcard | llama3.2:3b | Lateral thinker, unexpected connections |

## Debate Flow

1. User enters topic, picks domain (crypto/military), sets round count
2. Frontend opens WebSocket to `/ws/debate`, sends config JSON
3. Server sends `agents_config` with current agent list
4. **Rounds 1-2 (SOLO)**: Each agent gives independent take (no context from others)
5. **Rounds 3+ (DEBATE)**: Each agent sees all responses from the previous round and argues directly
6. Tokens stream in real time; user can pause/skip/stop at any point
7. On completion, "Debate Complete" banner shown

## Generation Parameters (M1 16GB optimized)

Set in `stream_ollama()` in `server.py`:
- `temperature: 1.0` -- higher creativity, more distinct agent voices
- `num_predict: 2500` -- enough for R1 think block (~400 tokens) + full response (~1500+ tokens)
- `num_ctx: 8192` -- full context window for long debate history in later rounds

## Grand Debate Synthesis Panel

After a debate completes, a "Grand Debate — Full Transcript" panel auto-renders and scrolls into view below the agent cards. It shows every round and every agent's response in chronological order, each entry highlighted with a left border in the agent's color. The panel is collapsible (click header to expand/collapse).

## Quick Persona Edit

Each agent card header has a small pencil icon (✎) that appears on hover. Clicking it opens a compact floating popover with:
- Agent name and emoji (readonly)
- Persona textarea (pre-filled with current persona)
- Save button (calls `PUT /api/agents/{id}`, persists to `agents.json`)
- Cancel button
- Escape key closes it

The edit is disabled with a tooltip during an active debate. The full "Manage Agents" modal is still available for name/emoji/color/model changes.

## What Has NOT Been Implemented Yet (from the original plan)

### Phase 3: Custom Domains + Flexible Prompts
- Domain is still hardcoded to crypto/military dropdown
- Planned: `domains.json` file, `GET/POST /api/domains`, custom domain creation from UI
- The backend prompt builders already have a fallback: `f"The domain is: {domain}."` for unknown domains

### Phase 4: Analysis + Transcript Export
- No transcript saving to disk
- No debate history
- No export (markdown/JSON)
- No word count, timing, or comparison stats
- Planned: `debates/` folder, `GET /api/debates`, analysis panel in UI

### Phase 5: UX/UI Polish
- No fullscreen mode for agent cards
- No sound notifications
- No dark/light theme toggle
- No agent timer (how long each agent has been generating)
- Keyboard shortcuts ARE done (Space, Escape, N)

## Tech Stack

- **Python 3**: FastAPI, uvicorn, httpx, websockets, pydantic
- **Frontend**: Vanilla HTML/CSS/JS (no framework, no build)
- **LLM Runtime**: Ollama (local, free)
- **Fonts**: Google Fonts (Space Mono + Syne)

## How to Run

```bash
cd "AI Debate"
chmod +x start.sh
./start.sh
# Opens at http://localhost:8765
```

## Key Implementation Details

### WebSocket Protocol

**Client -> Server messages:**
```json
// Initial config (first message after connect):
{"topic": "...", "domain": "crypto", "rounds": 3}

// During debate:
{"action": "pause"}
{"action": "resume"}
{"action": "stop"}
{"action": "skip"}
```

**Server -> Client message types:**
- `status` — Generic status message
- `agents_config` — List of agents for this debate (sent once at start)
- `round_start` — Round began (includes round number, mode)
- `agent_start` — Agent began generating (includes agent_id, round)
- `token` — Streaming token (includes agent_id, token text)
- `agent_done` — Agent finished (includes agent_id, round, skipped flag)
- `round_end` — Round completed
- `debate_paused` / `debate_resumed` — Control acknowledgments
- `debate_stopped` — Debate was manually stopped
- `debate_complete` — All rounds finished normally
- `error` — Error occurred

### Think Tag Filtering (server-side)

DeepSeek R1 models output `<think>...</think>` blocks. The `stream_ollama()` function uses a state machine:
- Buffers tokens, tracks `inside_think` boolean
- When `<think>` is detected, stops emitting tokens to WebSocket
- When `</think>` is detected, resumes emitting
- Edge case: partial tag matches held in buffer (up to 20 chars) to avoid split-tag bugs
- Client also has a fallback regex strip on `agent_done` for any residual

### Agent ID Generation

When creating agents via UI, the ID is derived from the name: lowercased, non-alphanumeric replaced with `_`. Duplicates get a random suffix appended.

## User Preferences

- Primary interest domains: **cryptocurrency/trading** and **military/defense technology**
- Wants to discuss diverse topics, not just those two
- Values accuracy over speed
- Wants easy agent role editing from the UI
- Runs everything locally on own hardware (free, no API keys)
- macOS (darwin 25.2.0)


Remaining phases (not done yet)
Phase 3: Custom domains (so you're not stuck with just crypto/military in the dropdown)
Phase 4: Transcript saving, debate history, export to markdown/JSON, analysis stats
Phase 5: UI polish (agent timers, fullscreen cards, sound notifications)
You can feed the progress/ folder to your next chat session and it'll pick up right where we left off.