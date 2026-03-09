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
├── server.py          # FastAPI backend (all logic, ~1022 lines)
├── index.html         # Full frontend (HTML + CSS + JS in one file, ~2130 lines)
├── agents.json        # Agent configurations (auto-created, editable via UI)
├── transcripts/       # Saved debate/ideation transcripts (JSON, auto-created)
├── start.sh           # Startup script (checks Ollama, installs deps, runs server)
├── README.md          # User-facing readme
└── progress/
    ├── SYSTEM_CONTEXT.md   # This file
    └── CHANGELOG.md        # Full change history
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

## Current Agents (4 total)

| Agent | Model | Role | Stance | Token Budget |
|---|---|---|---|---|
| The Inventor | r1-wild:latest | Creative ideation, non-obvious connections, revenue models | FOR | 800 |
| The Stress-Tester | huihui_ai/deepseek-r1-abliterated:8b | Finds fatal flaws, evolves ideas through pressure | AGAINST | 600 |
| The Builder | mistral:7b | Turns ideas into executable plans with costs/timelines | WILDCARD | 500 |
| The Provocateur | llama3.2:3b | Constraint injection, chaos agent, forces creativity | CATALYST | 400 |

**Persona Architecture**: Agent personas in `agents.json` contain only core identity paragraphs (who they are, how they think). All round-specific instructions, format headers, and output structure are handled server-side by `build_ideation_prompt()` and `build_debate_prompt()`. The `_IDENTITY_PREFIX` dict in `server.py` prepends identity lock + ROLE summary + format rules + think-block instructions to every system prompt as defence-in-depth.

## Ideation Pipeline Architecture (Data-Driven)

The ideation prompt system uses 3 declarative dicts instead of procedural if/elif chains:

### `AGENT_ROLE_PROMPTS`
Fixed output format per agent. Never changes regardless of topic. Defines the headers/structure each agent must follow (e.g., Inventor always outputs INSIGHT/IDEA/MECHANISM/ADVANTAGE/CONTRARIAN ANGLE).

### `ROUND_CONTEXT_MAP`
Declares which prior outputs to inject as context for each `(round, agent_id)` pair:
- `(1, "provocateur")`: no prior context
- `(2, "inventor")`: sees provocateur R1
- `(3, "builder")`: sees inventor R2
- `(4, "stress_tester")`: sees inventor R2 + builder R3
- `(5, "inventor")`: sees provocateur R1 + own R2 + stress_tester R4
- `(5, "builder")`: sees own R3 + stress_tester R4
- `(6, "*")`: `ALL_PRIOR` — all agents see everything from R1-R5

### `PHASE_DIRECTIVES`
One-line directive per `(round, agent_id)` telling the agent what to do with the context. R5 and R6 have per-agent directives (e.g., R5 inventor gets "MUTATION ROUND" with override format, R6 each agent gets a unique synthesis task).

### `build_ideation_prompt()`
The function is ~40 lines and assembles prompts mechanically:
- **System prompt** = `_IDENTITY_PREFIX[agent_id]` + `persona` (from agents.json)
- **User prompt** = `domain` + `topic` + auto-assembled context from `ROUND_CONTEXT_MAP` + directive from `PHASE_DIRECTIVES` + format from `AGENT_ROLE_PROMPTS` (skipped if directive has OVERRIDE FORMAT)

1. User enters topic, picks domain (crypto/military), sets round count
2. Frontend opens WebSocket to `/ws/debate`, sends config JSON
3. Server sends `agents_config` with current agent list
4. **Rounds 1-2 (SOLO)**: Each agent gives independent take (no context from others)
5. **Rounds 3+ (DEBATE)**: Each agent sees all responses from the previous round and argues directly
6. Tokens stream in real time; user can pause/skip/stop at any point
7. On completion, "Debate Complete" banner shown

## Generation Parameters (M1 16GB optimized)

All `num_ctx` is 4096 (8192 causes disk swapping on M1 16GB unified memory).

Per-agent token budgets via `AGENT_CFG` in `server.py`:
- Inventor: `num_predict=800` (needs room for think block + detailed ideas)
- Stress-Tester: `num_predict=600` (needs think block + flaw analysis)
- Builder: `num_predict=500` (no think block, structured output)
- Provocateur: `num_predict=400` (no think block, constraint format)
- Verdict: `num_predict=350` (extraction format, no creativity needed)

Think-block governor: `THINK_TOKEN_LIMIT=150` — after 150 tokens inside `<think>`, the governor silently eats remaining think tokens until `</think>` closes naturally.

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

### Debate Mode (DONE)

**Backend (server.py):**
- `VERDICT_MODEL = "mistral:7b"` — model used for judge verdict
- `AGENT_CFG` — per-agent token budgets (replaces old `DEBATE_CFG`), used in both debate and ideation
- `debate_stance` field added to all agent models and CRUD handlers
- `_extract_argument_log(history, agent_name)` — builds "DO NOT REPEAT" bullet list from prior turns
- `build_debate_prompt()` — 3-phase escalation: OPENING → CLASH (early/late) → CLOSING. Injects prior claims, opponent claims, phase directive. Smart history windowing: first 2 + last 4 turns.
- `generate_verdict()` — streams judge verdict from mistral:7b after all rounds complete
- WebSocket handler branches on `mode == "debate"` vs ideation
- `agents_config` message includes `mode` and `debate_stance` per agent

**Frontend (index.html):**
- Mode toggle (`💡 IDEATE` / `⚔️ DEBATE`)
- Rounds selector (4/6/8/10/12) shown in debate mode
- Debate topic chips (5 motions) / Ideate topic chips (5 ideas) — swapped per mode
- Stance badges (`.stance-for` green, `.stance-against` red, `.stance-wildcard` gold)
- Verdict panel (`#verdictPanel`) with streaming support and scroll-into-view
- Agent Manager: Debate Stance dropdown (FOR/AGAINST/WILDCARD)

### Phase 4: Transcript Storage + Export (DONE)

**Backend (server.py):**
- `TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"` (auto-created)
- `TranscriptPayload` Pydantic model
- `POST /api/transcript/save` — saves JSON to `transcripts/{timestamp}_{uuid}.json`
- `GET /api/transcripts` — lists all saved transcripts with id/topic/mode/rounds/timestamp
- `DELETE /api/transcripts/{tid}` — deletes by ID

**Frontend (index.html):**
- Export buttons on complete/stopped banners: **JSON**, **Markdown**, **Copy to Clipboard**, **Save to Server**
- `buildTranscriptData()` — builds structured transcript with agent timers included
- `exportTranscript('json'|'md'|'copy')` — file download or clipboard copy
- `saveToServer()` — POSTs to `/api/transcript/save`
- `showToast(message, type)` — 2.5s toast notification at bottom center

### Phase 5: UI Polish (DONE)

**Frontend (index.html):**
- **Agent timers** — live-ticking elapsed timer on each card during generation, final time shown after
- **Debounced rendering** — 16ms throttle on `renderAgentContent()` to prevent DOM thrashing
- **Scroll-to-active** — camera follows the speaking agent card on `agent_start`
- **Clickable round pips** — clicking a pip jumps all agent cards to that round
- **localStorage persistence** — topic, domain, mode restored on page reload

## What Has NOT Been Implemented Yet

### Phase 3: Custom Domains
- Domain is a free-text input (not a dropdown), works fine as-is
- Planned optional enhancement: `domains.json` with presets, `GET/POST /api/domains`

### Remaining Phase 5 Items
- **Fullscreen agent cards** — expand a single card to fill the viewport
- **Sound notifications** — chime when agent finishes, different tone for verdict
- **Dark/light theme toggle**
- **Markdown rendering** — render agent output as formatted markdown instead of plain `<br>`
- **Past Sessions browser** — modal to browse, view, and delete saved transcripts from `GET /api/transcripts`

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
{"topic": "...", "domain": "crypto", "mode": "ideate", "phases": 5}
{"topic": "...", "domain": "AI / Ethics", "mode": "debate", "rounds": 8}

// During debate:
{"action": "pause"}
{"action": "resume"}
{"action": "stop"}
{"action": "skip"}
```

**Server -> Client message types:**
- `status` — Generic status message
- `agents_config` — List of agents for this debate (sent once at start); includes `mode`, `total_phases`, `phases` map, `debate_stance` per agent
- `round_start` — Round began (includes round number, total, phase name)
- `agent_start` — Agent began generating (includes agent_id, agent_name, round, phase)
- `token` — Streaming token (includes agent_id, token text; agent_id `__verdict__` for judge)
- `agent_done` — Agent finished (includes agent_id, round, phase, skipped flag)
- `round_end` — Round completed
- `verdict_start` — Judge is deliberating (debate mode only)
- `verdict` — Final verdict text (debate mode only)
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
- macOS (darwin 25.2.0), M1 16GB
