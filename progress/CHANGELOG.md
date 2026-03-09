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

## Session 4 — Debate Mode (March 9, 2026)

### Debate Mode Implementation

**agents.json changes:**
- Added `debate_stance` field to all 3 current agents: `FOR` (Inventor), `AGAINST` (Stress-Tester), `WILDCARD` (Builder)
- Reduced to 3 agents tuned for debate (Inventor, Stress-Tester, Builder)

**server.py changes:**
- Added `VERDICT_MODEL = "mistral:7b"` constant
- Added `debate_stance` field to `DEFAULT_AGENTS`, `AgentUpdate`, `AgentCreate`, and all CRUD handlers
- Added `DEBATE_CFG = {"num_predict": 600, "num_ctx": 8192}`
- Added `build_debate_prompt()` — stance-aware prompt builder for debate turns
- Added `generate_verdict()` — streams a judge verdict via mistral:7b after all rounds
- Added debate mode branch inside WebSocket handler: sequential rounds with per-agent stance prompts, verdict at end
- `agents_config` message now includes `mode` and `debate_stance` per agent
- `phase_map` set to `R1..RN` labels in debate mode vs phase names in ideation mode

**index.html changes:**
- Mode toggle (`💡 IDEATE` / `⚔️ DEBATE`) with `setMode()` function
- Start button text and color change per mode
- Rounds selector (4/6/8/10/12) visible only in debate mode
- Debate topic chips (5 motions) shown in debate mode; ideate chips hidden
- Topic label changes to "Motion / Proposition" in debate mode
- Logo subtitle changes per mode
- Stance badge CSS (`.stance-for`, `.stance-against`, `.stance-wildcard`)
- Verdict panel HTML (`#verdictPanel`, `#verdictBody`) and streaming CSS
- `verdictText` accumulator for proper token streaming
- `serverMode` and `currentMode` state variables
- `renderArena()` shows stance badges under agent name in debate mode
- Agent round tabs show `R1..RN` labels in debate mode
- `handleMessage()` handles `verdict_start`, `verdict` with streaming + cursor
- Agent Manager modal: `Debate Stance` dropdown (FOR/AGAINST/WILDCARD)
- Stop button changed to "🛑 Stop"
- Empty state updates dynamically per mode
- Control panel grid: `1fr 200px auto auto`

## Session 5 — Anti-Repetition Fix + Phase 4 + Phase 5 (March 9, 2026)

### Core Fix: Anti-Repetition Debate Prompts

**server.py changes:**
- `DEBATE_CFG["num_predict"]`: 600 → 500 (forces tighter, denser arguments)
- Added `_extract_argument_log(history, agent_name)` helper — builds bullet list of each agent's prior claims and opponents' claims, injected as "DO NOT REPEAT THESE" directive
- Rewrote `build_debate_prompt()` with 3-phase escalation:
  - **OPENING** (round 1): establish position, lay out 2-3 strongest arguments
  - **CLASH early** (rounds 2..N/2): engage opponents, introduce new angles
  - **CLASH late** (rounds N/2..N-1): go deeper not wider, attack fundamental assumptions, concede minor points
  - **CLOSING** (final round): synthesize strongest points, demolish weakest opposing claim
- Smart history windowing: first 3 + last 6 turns (was: last 6 only) to preserve early context
- Last speaker text capped at 300 chars in prompt to save context budget
- Phase directive and agent's prior claims both injected into every prompt after round 1

### Phase 4: Transcript Storage + Export

**server.py changes:**
- Added `import time` to imports
- Added `TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"` constant
- Added `TranscriptPayload` Pydantic model
- Added `POST /api/transcript/save` — saves full transcript JSON to `transcripts/` folder
- Added `GET /api/transcripts` — lists all saved transcripts (id, topic, mode, rounds, timestamp)
- Added `DELETE /api/transcripts/{tid}` — deletes a saved transcript by ID
- `transcripts/` directory auto-created on server start

**index.html changes:**
- Export bar CSS (`.export-bar`, `.btn-export` with `.export-json/.export-md/.export-copy/.export-save` hover variants)
- Export buttons (JSON, Markdown, Copy to Clipboard, Save to Server) added to both `complete-banner` and `harvest-banner`
- `buildTranscriptData()` — assembles structured transcript object from all `agentData` including per-agent timers
- `exportTranscript('json')` — downloads `.json` file via Blob URL
- `exportTranscript('md')` — downloads `.md` file with full round/agent headers and verdict
- `exportTranscript('copy')` — copies plain-text transcript to clipboard
- `saveToServer()` — POSTs transcript to `/api/transcript/save`, shows confirmation toast
- `showToast(message, type)` — non-blocking bottom-center toast notification
- Toast CSS (`.toast`, `.toast-visible`, `.toast-success`, `.toast-error`) with 2.5s auto-dismiss
- Toast `<div id="toast">` element added outside `#app`

### Phase 5: UI Polish

**index.html changes:**
- **Agent timers**: `agentTimers` state object, timer starts on `agent_start`, live-updates every 100ms via `setInterval`, stops and displays final elapsed on `agent_done`. Timer displayed in `.agent-timer` span in card header.
- **Debounced rendering**: `renderAgentContent()` now debounces via `_renderTimers` at 16ms (one frame), delegates to `_doRenderAgentContent()`. Prevents DOM thrashing during high-speed token streaming.
- **Scroll-to-active**: `agent_start` handler calls `activeCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' })` so the camera follows the speaking agent.
- **Clickable round pips**: `updateRoundPips()` attaches `onclick = () => jumpToRound(i)` and `title` tooltip to each pip. `jumpToRound(round)` switches all agents' active tabs to that round simultaneously.
- **localStorage persistence**: `init()` restores `arena_topic`, `arena_domain`, `arena_mode` on page load. `setTopic()`, `setMode()`, and `startDebate()` all persist to localStorage on change.
- **State additions**: `agentTimers`, `_renderTimers`, `sessionStartTime`, `sessionTopic` added to JS state block.
- **Agent timer CSS** (`.agent-timer`, `.agent-timer.timing`)
- **Clickable pip CSS** (`.round-pip { cursor: pointer }` with hover scale)

## Session 6 — M1 Hardware Optimization (March 9, 2026)

### Token Budget & Context Window Optimization

**server.py changes:**
- All `num_ctx` set to 4096 (was 8192 for R3-R6) — prevents disk swapping on M1 16GB
- `IDEATION_PHASES` no longer carries `num_predict` — moved to per-agent `AGENT_CFG`
- Added `AGENT_CFG` dict: inventor=800, stress_tester=600, builder=500, provocateur=400
- Added `DEFAULT_AGENT_CFG = {"num_predict": 600, "num_ctx": 4096}`
- Added `VERDICT_CFG = {"num_predict": 350, "num_ctx": 4096}`
- Removed `DEBATE_CFG` constant — debate loop now uses `AGENT_CFG.get(agent["id"], DEFAULT_AGENT_CFG)`
- Ideation loop uses `AGENT_CFG` for `num_predict`, `IDEATION_PHASES` for `num_ctx`

### Think-Block Governor

- Added `THINK_TOKEN_LIMIT = 150` constant
- `stream_ollama()` now tracks `think_token_count` and `think_governor_active`
- After 150 tokens inside `<think>`, governor silently eats remaining think tokens
- Waits for natural `</think>` close, then resumes normal output

### Identity Prefix System

- Added `_IDENTITY_PREFIX` dict with entries for all 4 agents
- Each prefix includes: IDENTITY lock, ROLE summary, FORMAT rules
- Inventor and Stress-Tester get additional THINK BLOCK instruction
- Prepended to system prompt in both `build_ideation_prompt()` and `build_debate_prompt()`

### Debate Improvements

- History window changed from first 3 + last 6 to first 2 + last 4 (saves context budget)
- Verdict functions updated to use `VERDICT_CFG` instead of hardcoded 800/8192
- Ideation verdict changed to extraction analyst format with 9-field structured output

## Session 7 — Persona Cleanup + Tab Filtering (March 9, 2026)

### Step 1: Clean Agent Personas

**agents.json changes:**
- Stripped all round-specific instructions (ROUND 1: ..., ROUND 2 — THIS IS YOUR TURN: ...) from all 4 agents
- Removed hardcoded Quran-app content (constraints, ayat references, API mentions) from provocateur and other agents
- Personas reduced from ~1400-1700 chars → ~577-708 chars (pure identity only)
- `build_ideation_prompt()` is now the sole source of per-round behavior

**server.py changes:**
- Added `ROLE:` summary line to each agent's `_IDENTITY_PREFIX` (e.g., "ROLE: Creative ideation — generate novel ideas with specific mechanisms, revenue models, and contrarian angles.")

### Step 2: Frontend Round Tab Filtering

**index.html changes:**
- Added `.round-tab.observing` CSS: 30% opacity, italic, 👁 icon, pointer-events disabled
- Added `.round-tab.has-data` CSS: re-enables pointer events after data arrives
- `renderArena()` now uses `roundAgentMap` to mark non-participating round tabs as `.observing` in ideation mode
- `switchTab()` blocks switching to rounds the agent didn't participate in (unless tab has data)
- `_doRenderAgentContent()` shows "👁 Observing PHASE — not active this round" for non-participating rounds
- `jumpToRound()` respects `roundAgentMap` — only switches tabs for agents that participated
- `round_start` handler resets all card opacity to 1.0 before dimming inactive agents
- `agent_done` handler unlocks tabs by removing `.observing` and adding `.has-data`
- `agents_config` handler sets each agent's initial active tab to their first participating round

## Session 8 — Data-Driven Ideation Prompts (March 9, 2026)

### Step 3: Rework Ideation Prompt Architecture

**server.py changes:**
- Replaced 240-line `build_ideation_prompt()` if/elif chain with ~40-line data-driven function
- Added `AGENT_ROLE_PROMPTS` dict — fixed per-agent output format (headers/structure) that never changes per topic
- Added `ROUND_CONTEXT_MAP` dict — declares which prior `(agent_id, round)` outputs to inject per round/agent pair. Special value `"ALL_PRIOR"` for R6 gathers everything from R1-R5 automatically.
- Added `PHASE_DIRECTIVES` dict — one-line directive per `(round, agent_id)` telling the agent what to do with context. R5/R6 have per-agent directives with override formats.
- Added `_AGENT_NAMES` dict — human-readable names for context labels
- New function flow: system_prompt = identity_prefix + persona; user_prompt = domain + topic + auto-assembled context + directive + role format
- R5 MUTATE uses `OVERRIDE FORMAT` in directive to replace default role format with mutation-specific headers
- R6 SYNTHESIZE gives each agent a unique final task (novelty score / 60s pitch / risk YES-NO / 5 action steps)
- Context injection verified correct: R5 inventor sees provocateur R1 + own R2 + stress_tester R4 (not builder R3)

## Session 6 — M1 Hardware Optimization (March 9, 2026)

### M1 16GB Memory Optimization

**server.py changes:**
- All `num_ctx` values changed from 8192 to 4096 across the entire codebase (8192 causes disk swapping on M1 16GB unified memory)
- Removed `DEBATE_CFG` constant entirely
- Added `AGENT_CFG` — per-agent token budgets: inventor 800, stress_tester 600, builder 500, provocateur 400
- Added `DEFAULT_AGENT_CFG = {"num_predict": 600, "num_ctx": 4096}` for custom agents
- Added `VERDICT_CFG = {"num_predict": 350, "num_ctx": 4096}` for both verdict functions
- `IDEATION_PHASES` simplified: removed per-phase `num_predict` (now per-agent via `AGENT_CFG`)
- Debate WebSocket loop uses `AGENT_CFG.get(agent["id"], DEFAULT_AGENT_CFG)` instead of `DEBATE_CFG`
- Ideation loop uses `AGENT_CFG` for `num_predict`, `IDEATION_PHASES` for `num_ctx`
- Debate history window: first 2 + last 4 turns (was first 3 + last 6)

### Think-Block Governor

**server.py changes:**
- Added `THINK_TOKEN_LIMIT = 150` constant
- `stream_ollama()` now tracks `think_token_count` and `think_governor_active`
- After 150 tokens inside `<think>`, the governor activates: silently eats remaining think tokens
- Waits for natural `</think>` close, then resumes normal output
- Prevents think blocks from consuming the entire token budget

### Identity Prefix System

**server.py changes:**
- Added `_IDENTITY_PREFIX` dict with defence-in-depth identity locks for all 4 agents
- Each prefix includes: IDENTITY (never simulate other agents), FORMAT (start with headers, no preamble), and for R1 models: THINK BLOCK instruction
- Prepended to system prompt in both `build_ideation_prompt()` and `build_debate_prompt()`

### Ideation Verdict Format

**server.py changes:**
- `generate_ideation_verdict()` system prompt changed from "venture analyst" to "signal extraction analyst"
- Verdict format changed to 9-field extraction (added MECHANISM field, removed THE 10X PLAY)
- Instructs model to extract from pipeline output rather than invent new analysis

## Session 7 — Persona Cleanup + Ideation Tab Filtering (March 9, 2026)

### Step 1: Clean Agent Personas

**agents.json changes:**
- Stripped ALL round-specific instructions ("ROUND 1: Output only...", "ROUND 2 — THIS IS YOUR TURN:...") from all 4 agent personas
- Removed hardcoded Quran-app content baked into provocateur and other agents' personas
- Personas reduced from 1400-1700 chars to 577-708 chars (pure identity paragraphs only)
- Round-specific behavior is now the SOLE responsibility of `build_ideation_prompt()` in server.py
- No more duplication between persona text and server-side prompt builder

**server.py changes:**
- Enhanced `_IDENTITY_PREFIX` with per-agent ROLE summary line:
  - inventor: "Creative ideation — generate novel ideas with specific mechanisms, revenue models, and contrarian angles."
  - stress_tester: "Destructive analysis — find fatal flaws, cite real failures, propose specific fixes."
  - builder: "Execution planning — turn ideas into MVPs with specific tools, timelines, costs, and go/no-go metrics."
  - provocateur: "Constraint injection — impose unexpected limitations and 'what-if' scenarios."
- ROLE line ensures agent knows its archetype even with a minimal persona

### Step 2: Ideation Tab Filtering + Round Indicators

**index.html changes:**
- `renderArena()` now uses `roundAgentMap` to determine which tabs to show per agent:
  - Tabs for rounds the agent participates in: normal clickable tabs
  - Tabs for rounds the agent doesn't participate in: `.observing` class (grayed, italic, 👁 icon, pointer-events disabled)
- `switchTab()` now blocks switching to rounds the agent doesn't participate in (unless the tab has data)
- `_doRenderAgentContent()` shows "👁 Observing {phase} — not active this round" placeholder for non-participating rounds
- `jumpToRound()` respects `roundAgentMap` — only switches tabs for agents that participated in the clicked round
- `round_start` handler: resets ALL card opacity to 1.0 first, then dims inactive agents (fixes stale opacity from previous round)
- `agent_done` handler: removes `.observing` class and adds `.has-data` class on the tab that just got data
- `agents_config` handler: sets each agent's initial active tab to their first participating round (e.g., provocateur starts on PROVOKE tab, inventor on INVENT tab)
- New CSS classes: `.round-tab.observing` (opacity 0.3, italic, 👁 after pseudo-element), `.round-tab.has-data` (override pointer-events back to auto)
