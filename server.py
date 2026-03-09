import asyncio
import json
import re
import time
import uuid
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from pydantic import BaseModel
from typing import Optional

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

OLLAMA_BASE = "http://localhost:11434"
OLLAMA_URL = f"{OLLAMA_BASE}/api/generate"
AGENTS_FILE = Path(__file__).parent / "agents.json"
TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"
VERDICT_MODEL = "mistral:7b"

# ── Ideation Pipeline ─────────────────────────────────────────────────

IDEATION_PHASES = {
    1: {"name": "PROVOKE",     "num_ctx": 4096},
    2: {"name": "INVENT",      "num_ctx": 4096},
    3: {"name": "BUILD",       "num_ctx": 4096},
    4: {"name": "DESTROY",     "num_ctx": 4096},
    5: {"name": "MUTATE",      "num_ctx": 4096},
    6: {"name": "SYNTHESIZE",  "num_ctx": 4096},
}

# Per-agent token budgets (M1 16GB optimized)
AGENT_CFG = {
    "inventor":      {"num_predict": 800, "num_ctx": 4096},
    "stress_tester": {"num_predict": 600, "num_ctx": 4096},
    "builder":       {"num_predict": 500, "num_ctx": 4096},
    "provocateur":   {"num_predict": 400, "num_ctx": 4096},
}
DEFAULT_AGENT_CFG = {"num_predict": 600, "num_ctx": 4096}
VERDICT_CFG       = {"num_predict": 350, "num_ctx": 4096}
THINK_TOKEN_LIMIT = 150

# Round → which agent IDs participate
ROUND_AGENT_MAP = {
    1: ["provocateur"],
    2: ["inventor"],
    3: ["builder"],
    4: ["stress_tester"],
    5: ["inventor", "builder"],
    6: ["provocateur", "inventor", "stress_tester", "builder"],
}

# ── Identity Prefixes (defence-in-depth, prepended to system prompt) ──

_IDENTITY_PREFIX = {
    "inventor": (
        "IDENTITY: You are The Inventor and ONLY The Inventor. "
        "Never simulate, quote, or role-play any other agent.\n"
        "ROLE: Creative ideation — generate novel ideas with specific "
        "mechanisms, revenue models, and contrarian angles.\n"
        "FORMAT: Start with the required header for this round. "
        "No preamble, no 'Sure!', no meta-commentary.\n"
        "THINK BLOCK: Keep <think> reasoning under 150 tokens. Get to output fast.\n\n"
    ),
    "stress_tester": (
        "IDENTITY: You are The Stress-Tester and ONLY The Stress-Tester. "
        "Never simulate, quote, or role-play any other agent.\n"
        "ROLE: Destructive analysis — find fatal flaws, cite real failures, "
        "propose specific fixes for every flaw you identify.\n"
        "FORMAT: Start with the required header for this round. "
        "No preamble, no 'Sure!', no meta-commentary.\n"
        "THINK BLOCK: Keep <think> reasoning under 150 tokens. Get to output fast.\n\n"
    ),
    "builder": (
        "IDENTITY: You are The Builder and ONLY The Builder. "
        "Never simulate, quote, or role-play any other agent.\n"
        "ROLE: Execution planning — turn ideas into MVPs with specific "
        "tools, timelines, costs, and go/no-go metrics.\n"
        "FORMAT: Start with the required header for this round. "
        "No preamble, no 'Sure!', no meta-commentary.\n\n"
    ),
    "provocateur": (
        "IDENTITY: You are The Provocateur and ONLY The Provocateur. "
        "Never simulate, quote, or role-play any other agent.\n"
        "ROLE: Constraint injection — impose unexpected limitations and "
        "'what-if' scenarios that force non-obvious creative directions.\n"
        "FORMAT: Start with the required header for this round. "
        "No preamble, no 'Sure!', no meta-commentary.\n\n"
    ),
}

# ── Default Agents ────────────────────────────────────────────────────

DEFAULT_AGENTS = [
    {
        "id": "inventor",
        "name": "The Inventor",
        "emoji": "💡",
        "model": "r1-wild:latest",
        "color": "#ff6b35",
        "temperature": 1.2,
        "debate_stance": "FOR",
        "persona": (
            "You are The Inventor — a relentless creative engine that finds "
            "opportunity where others see nothing. You combine technologies, "
            "markets, and human behaviors in ways nobody has connected before. "
            "You think like a patent holder, a startup founder, and a futurist "
            "simultaneously. Every idea you propose must have a clear mechanism "
            "for making money or creating measurable value. You never propose "
            "vague concepts — you name the specific technology, the specific "
            "market gap, and the specific revenue model. You are bold and "
            "contrarian: if everyone is zigging, you explain why zagging is "
            "the real play. Draw from any field — biology, physics, military "
            "strategy, behavioral economics — to find non-obvious connections."
        ),
    },
    {
        "id": "stress_tester",
        "name": "The Stress-Tester",
        "emoji": "🔥",
        "model": "huihui_ai/deepseek-r1-abliterated:8b-llama-distill",
        "color": "#ff3366",
        "temperature": 0.9,
        "debate_stance": "AGAINST",
        "persona": (
            "You are The Stress-Tester — a ruthless but constructive critic "
            "who finds every fatal flaw, market risk, and hidden assumption "
            "in an idea. You have studied hundreds of failed startups, bankrupt "
            "companies, and abandoned projects. You know the five reasons most "
            "ideas die: no market, no moat, bad timing, wrong team, wrong "
            "economics. BUT you are not just a destroyer — for every flaw you "
            "find, you MUST propose a specific fix, pivot, or mitigation. You "
            "evolve ideas through pressure, like a blacksmith hammering steel. "
            "Name real competitors, cite real market dynamics, reference real "
            "failure cases. If an idea survives your stress test, it is "
            "genuinely worth building."
        ),
    },
    {
        "id": "builder",
        "name": "The Builder",
        "emoji": "🔧",
        "model": "mistral:7b",
        "color": "#00ff88",
        "temperature": 0.8,
        "debate_stance": "WILDCARD",
        "persona": (
            "You are The Builder — you turn ideas into executable plans with "
            "specific tools, timelines, costs, and metrics. While others dream "
            "and debate, you ask: what do we build first? What tools do we use? "
            "How much does it cost? How do we know it is working? You think in "
            "MVPs, iteration cycles, and unit economics. You name specific "
            "platforms (AWS, Stripe, Vercel, Hugging Face, etc.), specific "
            "frameworks, specific APIs. You estimate costs to the nearest $100 "
            "and timelines to the nearest week. You are the person who actually "
            "ships. Abstract advice is worthless — you give the actual "
            "step-by-step playbook that someone can start executing tomorrow "
            "morning."
        ),
    },
    {
        "id": "provocateur",
        "name": "The Provocateur",
        "emoji": "🎲",
        "model": "llama3.2:3b",
        "color": "#a855f7",
        "temperature": 1.4,
        "debate_stance": "CATALYST",
        "persona": (
            "You are The Provocateur — a constraint injector and chaos agent "
            "who forces creativity by imposing unexpected limitations, "
            "absurd-but-real market angles, and 'what-if' scenarios that nobody "
            "else would consider. You never propose safe ideas. You ask the "
            "dangerous questions: What if this had to work without the internet? "
            "What if the customer is a government? What if this needs to be "
            "illegal to be profitable? You draw from edge cases, black swan "
            "events, regulatory loopholes, and contrarian market timing. Your "
            "job is to break the frame so others can build something truly new."
        ),
    },
]


def load_agents() -> list[dict]:
    if AGENTS_FILE.exists():
        try:
            data = json.loads(AGENTS_FILE.read_text())
            if isinstance(data, list) and len(data) > 0:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    save_agents(DEFAULT_AGENTS)
    return DEFAULT_AGENTS[:]


def save_agents(agents: list[dict]):
    AGENTS_FILE.write_text(json.dumps(agents, indent=2, ensure_ascii=False))


AGENTS: list[dict] = load_agents()

# Auto-migrate: ensure Provocateur exists
if not any(a.get("id") == "provocateur" for a in AGENTS):
    _prov = next((a for a in DEFAULT_AGENTS if a["id"] == "provocateur"), None)
    if _prov:
        AGENTS.append(_prov.copy())
        save_agents(AGENTS)


# ── Model Discovery ──────────────────────────────────────────────────

@app.get("/api/models")
async def get_models():
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{OLLAMA_BASE}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = []
            for m in data.get("models", []):
                models.append({
                    "name": m.get("name", ""),
                    "size": m.get("size", 0),
                    "parameter_size": m.get("details", {}).get("parameter_size", ""),
                    "family": m.get("details", {}).get("family", ""),
                    "quantization": m.get("details", {}).get("quantization_level", ""),
                })
            return models
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"Cannot reach Ollama: {str(e)}"}
        )


# ── Agent CRUD ────────────────────────────────────────────────────────

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    emoji: Optional[str] = None
    model: Optional[str] = None
    color: Optional[str] = None
    persona: Optional[str] = None
    temperature: Optional[float] = None
    debate_stance: Optional[str] = None


class AgentCreate(BaseModel):
    name: str
    emoji: str = "🤖"
    model: str
    color: str = "#888888"
    persona: str = "You are a creative problem solver. Be specific and actionable."
    temperature: float = 1.0
    debate_stance: str = "WILDCARD"


@app.get("/api/agents")
async def api_get_agents():
    return AGENTS


@app.post("/api/agents")
async def api_save_all_agents(agents: list[dict]):
    global AGENTS
    AGENTS = agents
    save_agents(AGENTS)
    return {"ok": True, "count": len(AGENTS)}


@app.post("/api/agents/new")
async def api_create_agent(agent: AgentCreate):
    global AGENTS
    new_id = re.sub(r'[^a-z0-9_]', '', agent.name.lower().replace(" ", "_"))
    existing_ids = {a["id"] for a in AGENTS}
    if new_id in existing_ids:
        new_id = f"{new_id}_{uuid.uuid4().hex[:4]}"
    new_agent = {
        "id": new_id,
        "name": agent.name,
        "emoji": agent.emoji,
        "model": agent.model,
        "color": agent.color,
        "persona": agent.persona,
        "temperature": agent.temperature,
        "debate_stance": agent.debate_stance,
    }
    AGENTS.append(new_agent)
    save_agents(AGENTS)
    return new_agent


@app.put("/api/agents/{agent_id}")
async def api_update_agent(agent_id: str, update: AgentUpdate):
    global AGENTS
    for agent in AGENTS:
        if agent["id"] == agent_id:
            if update.name is not None:
                agent["name"] = update.name
            if update.emoji is not None:
                agent["emoji"] = update.emoji
            if update.model is not None:
                agent["model"] = update.model
            if update.color is not None:
                agent["color"] = update.color
            if update.persona is not None:
                agent["persona"] = update.persona
            if update.temperature is not None:
                agent["temperature"] = update.temperature
            if update.debate_stance is not None:
                agent["debate_stance"] = update.debate_stance
            save_agents(AGENTS)
            return agent
    return JSONResponse(status_code=404, content={"error": "Agent not found"})


@app.delete("/api/agents/{agent_id}")
async def api_delete_agent(agent_id: str):
    global AGENTS
    before = len(AGENTS)
    AGENTS = [a for a in AGENTS if a["id"] != agent_id]
    if len(AGENTS) < before:
        save_agents(AGENTS)
        return {"ok": True, "remaining": len(AGENTS)}
    return JSONResponse(status_code=404, content={"error": "Agent not found"})


# ── Think-tag filtering + Ollama streaming ────────────────────────────

THINK_OPEN = re.compile(r"<think>", re.IGNORECASE)
THINK_CLOSE = re.compile(r"</think>", re.IGNORECASE)


async def stream_ollama(
    model: str,
    prompt: str,
    ws: WebSocket,
    agent_id: str,
    cancel_event: asyncio.Event,
    system_prompt: str = "",
    temperature: float = 1.0,
    num_predict: int = 1200,
    num_ctx: int = 8192,
):
    """Stream from Ollama with <think> filtering and system prompt support."""
    full_response = ""
    clean_response = ""
    inside_think = False
    think_buffer = ""
    think_token_count = 0
    think_governor_active = False

    try:
        request_body = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
                "num_ctx": num_ctx,
            },
        }
        if system_prompt:
            request_body["system"] = system_prompt

        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream("POST", OLLAMA_URL, json=request_body) as response:
                async for line in response.aiter_lines():
                    if cancel_event.is_set():
                        break
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        token = data.get("response", "")
                        if not token:
                            if data.get("done"):
                                break
                            continue

                        full_response += token
                        think_buffer += token

                        # Think-block governor: after limit, eat until </think>
                        if think_governor_active:
                            close_match = THINK_CLOSE.search(think_buffer)
                            if close_match:
                                think_governor_active = False
                                inside_think = False
                                think_token_count = 0
                                think_buffer = think_buffer[close_match.end():]
                                if not think_buffer:
                                    continue
                            else:
                                think_buffer = think_buffer[-20:]
                                continue

                        while think_buffer:
                            if inside_think:
                                think_token_count += 1
                                if think_token_count >= THINK_TOKEN_LIMIT:
                                    think_governor_active = True
                                    think_buffer = think_buffer[-20:]
                                    break
                                close_match = THINK_CLOSE.search(think_buffer)
                                if close_match:
                                    inside_think = False
                                    think_token_count = 0
                                    think_buffer = think_buffer[close_match.end():]
                                else:
                                    if len(think_buffer) > 20:
                                        think_buffer = think_buffer[-20:]
                                    break
                            else:
                                open_match = THINK_OPEN.search(think_buffer)
                                if open_match:
                                    emit = think_buffer[:open_match.start()]
                                    if emit:
                                        clean_response += emit
                                        await ws.send_json({
                                            "type": "token",
                                            "agent_id": agent_id,
                                            "token": emit,
                                        })
                                    inside_think = True
                                    think_buffer = think_buffer[open_match.end():]
                                else:
                                    safe = think_buffer[:-7] if len(think_buffer) > 7 else ""
                                    if safe:
                                        clean_response += safe
                                        await ws.send_json({
                                            "type": "token",
                                            "agent_id": agent_id,
                                            "token": safe,
                                        })
                                        think_buffer = think_buffer[len(safe):]
                                    break

                        if data.get("done"):
                            break
                    except json.JSONDecodeError:
                        pass

        # Flush remaining buffer
        if think_buffer and not inside_think:
            clean_response += think_buffer
            await ws.send_json({
                "type": "token",
                "agent_id": agent_id,
                "token": think_buffer,
            })

    except Exception as e:
        if not cancel_event.is_set():
            await ws.send_json({
                "type": "token",
                "agent_id": agent_id,
                "token": f"\n[Error: {str(e)}]",
            })
    return clean_response


# ── Ideation Prompt Builder ────────────────────────────────────────────

# Fixed output format per agent — never changes regardless of topic.
# These tell each agent HOW to structure their response.
AGENT_ROLE_PROMPTS = {
    "provocateur": (
        "OUTPUT FORMAT (follow exactly):\n"
        "CONSTRAINT 1: [one-line constraint]\n"
        "WHY IT MATTERS: [2 sentences max]\n\n"
        "CONSTRAINT 2: [one-line constraint]\n"
        "WHY IT MATTERS: [2 sentences max]\n\n"
        "CONSTRAINT 3: [one-line constraint]\n"
        "WHY IT MATTERS: [2 sentences max]\n\n"
        "Make them specific, real, and uncomfortable. No generic 'think outside "
        "the box' — give concrete constraints from real markets, regulations, or physics."
    ),
    "inventor": (
        "OUTPUT FORMAT (follow exactly):\n"
        "INSIGHT: [The non-obvious connection or market gap you spotted]\n"
        "IDEA: [Punchy one-line name]\n"
        "MECHANISM: [How it works — specific technology, platform, or process]\n"
        "ADVANTAGE: [Why this beats what exists — name the competitor or alternative]\n"
        "CONTRARIAN ANGLE: [What everyone else gets wrong about this space]\n\n"
        "Be specific: name real tools, real companies, real price points."
    ),
    "builder": (
        "OUTPUT FORMAT (follow exactly):\n"
        "MVP: [What the minimum viable version looks like — 3-4 sentences]\n"
        "TIMELINE: [Week-by-week for first 4 weeks]\n"
        "COST: [Estimated cost to reach MVP, broken down by category]\n"
        "STACK: [Specific tools, APIs, platforms, frameworks]\n"
        "ASSUMPTION: [The single biggest assumption this plan depends on]\n"
        "FIRST DOLLAR: [How and when this makes its first revenue]\n\n"
        "No abstract advice. Every line must be actionable starting tomorrow."
    ),
    "stress_tester": (
        "OUTPUT FORMAT (follow exactly for each flaw):\n"
        "FLAW 1: [Name]\n"
        "SOURCE: [Market, technical, economic, regulatory, or competitive]\n"
        "EVIDENCE: [Specific data point, competitor, or historical example]\n"
        "KILL CONDITION: [What happens if this flaw is not addressed]\n"
        "FIX: [Specific mitigation — not 'do more research' but an actual pivot or solution]\n\n"
        "FLAW 2: ...\n\nFLAW 3: ...\n\n"
        "Be ruthless but constructive. Every flaw must come with a real fix."
    ),
}

# Which prior outputs to inject as context for each (round, agent_id).
# "*" as agent_id means "all agents in this round get the same context".
# Each entry is a list of (agent_id, round_num) tuples to pull from all_responses.
# Special value "ALL_PRIOR" means gather everything from rounds 1..current-1.
ROUND_CONTEXT_MAP: dict[tuple[int, str], list] = {
    (1, "provocateur"):   [],
    (2, "inventor"):      [("provocateur", 1)],
    (3, "builder"):       [("inventor", 2)],
    (4, "stress_tester"): [("inventor", 2), ("builder", 3)],
    (5, "inventor"):      [("provocateur", 1), ("inventor", 2), ("stress_tester", 4)],
    (5, "builder"):       [("builder", 3), ("stress_tester", 4)],
    (6, "*"):             "ALL_PRIOR",
}

# Agent-friendly names for context labels
_AGENT_NAMES = {
    "provocateur": "The Provocateur",
    "inventor": "The Inventor",
    "builder": "The Builder",
    "stress_tester": "The Stress-Tester",
}

# One-line directive per (round, agent_id) — tells the agent WHAT to do
# with the context this round. Keeps the core role prompt stable.
PHASE_DIRECTIVES: dict[tuple[int, str], str] = {
    # R1: PROVOKE — no prior context
    (1, "provocateur"): (
        "PROVOCATION ROUND — Inject constraints that force creativity. "
        "Deliver exactly 3 provocative constraints or 'what-if' scenarios "
        "that will push the other agents beyond the obvious."
    ),
    # R2: INVENT — sees provocateur constraints
    (2, "inventor"): (
        "INVENTION ROUND — Using the constraints above as creative fuel, "
        "generate ONE powerful idea. Not three. ONE — your absolute best."
    ),
    # R3: BUILD — sees inventor's idea
    (3, "builder"): (
        "BUILD ROUND — Turn this idea into an executable plan."
    ),
    # R4: DESTROY — sees idea + build plan
    (4, "stress_tester"): (
        "DESTRUCTION ROUND — Find exactly 3 fatal flaws. Not nitpicks — "
        "genuine kill shots that could sink this idea."
    ),
    # R5: MUTATE — inventor mutates idea, builder revises plan
    (5, "inventor"): (
        "MUTATION ROUND — Your original idea has been stress-tested. "
        "Now MUTATE it: absorb the valid criticisms, keep the core insight, "
        "and produce a stronger version.\n\n"
        "OVERRIDE FORMAT FOR THIS ROUND:\n"
        "WHAT SURVIVED: [Core insight that remains valid]\n"
        "WHAT CHANGED: [How you addressed the flaws]\n"
        "MUTATED IDEA: [Full description of the evolved concept]\n"
        "NEW ADVANTAGE: [Why this version is harder to kill]"
    ),
    (5, "builder"): (
        "REVISION ROUND — Your build plan has been stress-tested. "
        "Revise it: fix the vulnerabilities, adjust the timeline and costs, "
        "and produce a battle-hardened version.\n\n"
        "OVERRIDE FORMAT FOR THIS ROUND:\n"
        "REVISED MVP: [Updated minimum viable version]\n"
        "REVISED TIMELINE: [Updated week-by-week]\n"
        "REVISED COST: [Updated budget]\n"
        "RISK MITIGATIONS: [How each identified flaw is now handled]\n"
        "GO/NO-GO SIGNAL: [The metric at week 4 that tells you to continue or pivot]"
    ),
    # R6: SYNTHESIZE — each agent has a unique final job
    (6, "provocateur"): (
        "SYNTHESIS ROUND — Deliver your FINAL VERDICT on whether this idea "
        "is truly novel or just a rehash. Score the novelty 1-10 and explain why. "
        "What would make it a genuine 10?"
    ),
    (6, "inventor"): (
        "SYNTHESIS ROUND — Deliver your FINAL SYNTHESIS: the definitive version "
        "of this idea after all pressure-testing and mutation. One paragraph, "
        "crystal clear, ready to pitch to an investor in 60 seconds."
    ),
    (6, "stress_tester"): (
        "SYNTHESIS ROUND — Deliver your FINAL RISK ASSESSMENT. "
        "After seeing the mutations and revisions, what is the remaining #1 risk? "
        "Has this idea earned the right to be built? YES or NO, with your reason."
    ),
    (6, "builder"): (
        "SYNTHESIS ROUND — Deliver your FINAL ACTION PLAN. "
        "Exactly 5 steps, starting tomorrow, to move this from idea to reality. "
        "Include specific tools, costs, and who does what."
    ),
}


def build_ideation_prompt(
    round_num: int,
    agent: dict,
    topic: str,
    domain: str,
    all_responses: dict,
) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) using the data-driven dicts.

    System prompt = identity prefix + agent persona (from agents.json)
    User prompt   = domain + topic + auto-assembled context + directive + format
    """
    agent_id = agent.get("id", "")

    # ── System prompt: identity + persona (never changes per round) ──
    system_prompt = (
        _IDENTITY_PREFIX.get(agent_id, "")
        + agent.get("persona", "You are a creative problem solver.")
    )

    # ── Assemble context from prior rounds ──
    context_spec = ROUND_CONTEXT_MAP.get(
        (round_num, agent_id),
        ROUND_CONTEXT_MAP.get((round_num, "*"), []),
    )

    context_parts: list[str] = []
    if context_spec == "ALL_PRIOR":
        for r in range(1, round_num):
            for aid in ROUND_AGENT_MAP.get(r, []):
                text = all_responses.get((aid, r), "")
                if text.strip():
                    name = _AGENT_NAMES.get(aid, aid)
                    phase = IDEATION_PHASES.get(r, {}).get("name", f"R{r}")
                    context_parts.append(f"[{name} — {phase}]:\n{text}")
    elif isinstance(context_spec, list):
        for aid, r in context_spec:
            text = all_responses.get((aid, r), "")
            if text.strip():
                name = _AGENT_NAMES.get(aid, aid)
                phase = IDEATION_PHASES.get(r, {}).get("name", f"R{r}")
                context_parts.append(f"[{name} — {phase}]:\n{text}")

    context_block = ""
    if context_parts:
        context_block = "CONTEXT:\n" + "\n\n".join(context_parts) + "\n\n"

    # ── Directive: what to do this round ──
    directive = PHASE_DIRECTIVES.get(
        (round_num, agent_id),
        PHASE_DIRECTIVES.get((round_num, "*"), "Continue building on the discussion."),
    )

    # ── Role format: default output structure (skipped if directive has OVERRIDE FORMAT) ──
    role_format = ""
    if "OVERRIDE FORMAT" not in directive:
        role_format = "\n\n" + AGENT_ROLE_PROMPTS.get(agent_id, "")

    # ── Build final user prompt ──
    domain_ctx = (
        f"Domain: {domain}. "
        "Ground every claim in real companies, real markets, real technology."
    )

    user_prompt = (
        f"{domain_ctx}\n\n"
        f"Topic: {topic}\n\n"
        f"{context_block}"
        f"{directive}"
        f"{role_format}"
    )

    return system_prompt, user_prompt


# ── Debate Prompt Builder ─────────────────────────────────────────────

def _extract_argument_log(history: list[tuple[str, str]], agent_name: str) -> str:
    """Build a bullet list of claims already made, so the model can avoid repeating them."""
    own_points: list[str] = []
    other_points: list[str] = []
    for name, text in history:
        if not text.strip():
            continue
        # Take first 120 chars as a summary of the argument's core claim
        summary = text.strip().replace("\n", " ")[:120]
        if name == agent_name:
            own_points.append(summary)
        else:
            other_points.append(f"{name}: {summary}")
    lines: list[str] = []
    if own_points:
        lines.append("YOUR PREVIOUS ARGUMENTS (DO NOT REPEAT THESE — escalate, deepen, or pivot):")
        for p in own_points[-4:]:
            lines.append(f"  • {p}")
    if other_points:
        lines.append("OPPONENTS' RECENT CLAIMS (address these directly):")
        for p in other_points[-4:]:
            lines.append(f"  • {p}")
    return "\n".join(lines)


def build_debate_prompt(
    agent: dict,
    motion: str,
    domain: str,
    round_num: int,
    total_rounds: int,
    prev_speaker_name: str,
    prev_speaker_text: str,
    full_history: list[tuple[str, str]],
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for a debate turn.

    Uses 3-phase escalation:
      OPENING  (round 1)           — establish position
      CLASH    (rounds 2 to N-1)   — engage, counter, deepen
      CLOSING  (final round)       — strongest closing argument
    """
    stance = agent.get("debate_stance", "WILDCARD")
    persona = agent.get("persona", "You are a sharp debater.")
    agent_name = agent.get("name", "Agent")

    stance_instruction = {
        "FOR": "You SUPPORT this motion. Build the strongest possible case FOR it.",
        "AGAINST": "You OPPOSE this motion. Build the strongest possible case AGAINST it.",
        "WILDCARD": "You are the WILDCARD. You may agree, disagree, redirect, or introduce a completely unexpected angle.",
    }.get(stance, "Debate freely.")

    # ── Determine debate phase ────────────────────────────────
    if round_num == 1:
        phase = "OPENING"
        phase_directive = (
            "This is your OPENING STATEMENT. Present your position clearly and powerfully. "
            "Lay out your 2-3 strongest arguments with concrete evidence. Set the tone."
        )
    elif round_num >= total_rounds:
        phase = "CLOSING"
        phase_directive = (
            "This is your CLOSING ARGUMENT — your final chance to persuade. "
            "Synthesize your strongest points, demolish the opposition's weakest claim, "
            "and end with a powerful conclusion. No new evidence — drive it home."
        )
    else:
        phase = "CLASH"
        progress = round_num / total_rounds
        if progress < 0.5:
            phase_directive = (
                "CLASH PHASE — Directly engage with opponents' arguments. "
                "Pick apart their weakest claim with specific counter-evidence. "
                "Introduce ONE new angle or piece of evidence they haven't addressed."
            )
        else:
            phase_directive = (
                "LATE CLASH — The debate is heating up. Go deeper, not wider. "
                "Find the fundamental assumption behind an opponent's argument and attack it. "
                "Use analogies, data, or real-world examples they can't easily dismiss. "
                "Concede a minor point if it strengthens your core position."
            )

    # ── System prompt ─────────────────────────────────────────
    system_prompt = (
        f"{_IDENTITY_PREFIX.get(agent.get('id', ''), '')}"
        f"{persona}\n\n"
        f"DEBATE STANCE: {stance}\n"
        f"{stance_instruction}\n\n"
        f"PHASE: {phase} (Round {round_num}/{total_rounds})\n"
        f"{phase_directive}\n\n"
        "CRITICAL RULES:\n"
        "• 3-5 sentences maximum. Dense, specific, no filler.\n"
        "• NEVER repeat an argument you already made — escalate or pivot.\n"
        "• NEVER restate the motion — go straight to your argument.\n"
        "• Name specific evidence: real companies, data points, historical examples.\n"
        "• If you catch yourself agreeing with everyone, find the contrarian angle."
    )

    # ── User prompt ───────────────────────────────────────────
    if round_num == 1 and not prev_speaker_text:
        user_prompt = (
            f"Domain: {domain}\n\n"
            f"THE MOTION: \"{motion}\"\n\n"
            "Deliver your opening statement."
        )
    else:
        # Smart history window: first 2 turns (context) + last 4 turns (recency)
        if len(full_history) > 6:
            window = full_history[:2] + full_history[-4:]
        else:
            window = full_history[:]

        history_text = "\n\n".join(
            f"[{name}]: {msg}" for name, msg in window if msg.strip()
        )

        arg_log = _extract_argument_log(full_history, agent_name)

        user_prompt = (
            f"Domain: {domain}\n\n"
            f"THE MOTION: \"{motion}\"\n\n"
            f"Round {round_num} of {total_rounds}.\n\n"
        )

        if history_text:
            user_prompt += f"DEBATE HISTORY:\n{history_text}\n\n"

        if arg_log:
            user_prompt += f"{arg_log}\n\n"

        if prev_speaker_text:
            user_prompt += (
                f"LAST SPEAKER ({prev_speaker_name}):\n"
                f"\"{prev_speaker_text[:300]}\"\n\n"
            )

        user_prompt += "Your response:"

    return system_prompt, user_prompt


async def generate_verdict(
    motion: str,
    full_transcript: list[tuple[str, str, str]],
    ws: WebSocket,
    cancel_event: asyncio.Event,
) -> str:
    """Generate a verdict by streaming from the judge model.
    full_transcript is list of (agent_name, stance, text)."""

    transcript_text = "\n\n".join(
        f"[{name} ({stance})]: {text}"
        for name, stance, text in full_transcript
        if text.strip()
    )

    system_prompt = (
        "You are a neutral, expert debate judge. You evaluate arguments based on "
        "logical rigor, evidence quality, rhetorical effectiveness, and practical insight. "
        "You are fair but decisive."
    )

    user_prompt = (
        f"THE MOTION: \"{motion}\"\n\n"
        f"FULL DEBATE TRANSCRIPT:\n{transcript_text}\n\n"
        "DELIVER YOUR VERDICT:\n"
        "1. Who made the strongest overall case and why? (Name the agent)\n"
        "2. What was the single most compelling argument made by anyone?\n"
        "3. What was the weakest argument or biggest logical flaw?\n"
        "4. Your final ruling: Does the motion STAND or FALL based on this debate?\n\n"
        "Be specific. Reference exact arguments. 1-2 paragraphs."
    )

    verdict_text = await stream_ollama(
        VERDICT_MODEL,
        user_prompt,
        ws,
        "__verdict__",
        cancel_event,
        system_prompt=system_prompt,
        temperature=0.7,
        num_predict=VERDICT_CFG["num_predict"],
        num_ctx=VERDICT_CFG["num_ctx"],
    )

    return verdict_text


async def generate_ideation_verdict(
    topic: str,
    domain: str,
    all_responses: dict,
    ws: WebSocket,
    cancel_event: asyncio.Event,
) -> str:
    """Generate a venture analyst brief for the ideation pipeline."""
    agent_names = {
        "provocateur": "The Provocateur",
        "inventor": "The Inventor",
        "builder": "The Builder",
        "stress_tester": "The Stress-Tester",
    }
    parts = []
    for r in range(1, 7):
        phase_name = IDEATION_PHASES.get(r, {}).get("name", f"R{r}")
        for aid in ROUND_AGENT_MAP.get(r, []):
            text = all_responses.get((aid, r), "")
            if text.strip():
                name = agent_names.get(aid, aid)
                parts.append(f"[{name} — {phase_name}]:\n{text}")

    transcript_text = "\n\n".join(parts)

    system_prompt = (
        "You are a signal extraction analyst. Your job is to extract and structure "
        "the key findings from the ideation pipeline into a standardized brief. "
        "Do not invent new ideas — extract what the agents produced. "
        "Be precise, be cold, omit nothing material."
    )

    user_prompt = (
        f"Topic: {topic}\nDomain: {domain}\n\n"
        f"FULL IDEATION PIPELINE OUTPUT:\n{transcript_text}\n\n"
        "EXTRACT into this exact format (no extra commentary):\n\n"
        "IDEA NAME: [extract the core idea name from the pipeline]\n"
        "WHAT IT IS: [2 sentences max — what the agents converged on]\n"
        "MECHANISM: [how it works technically — extract from Inventor + Builder]\n"
        "REVENUE MODEL: [how it makes money — extract from Inventor]\n"
        "BUILD COST: [extract from Builder's estimate]\n"
        "TIME TO REVENUE: [extract from Builder's timeline]\n"
        "FATAL RISK: [extract the #1 surviving risk from Stress-Tester]\n"
        "VERDICT: BUILD IT / PIVOT / KILL IT\n"
        "REASON: [2-3 sentences synthesizing the pipeline's conclusion]\n"
    )

    return await stream_ollama(
        VERDICT_MODEL,
        user_prompt,
        ws,
        "__verdict__",
        cancel_event,
        system_prompt=system_prompt,
        temperature=0.6,
        num_predict=VERDICT_CFG["num_predict"],
        num_ctx=VERDICT_CFG["num_ctx"],
    )


# ── Debate WebSocket ──────────────────────────────────────────────────

@app.websocket("/ws/debate")
async def debate_websocket(websocket: WebSocket):
    await websocket.accept()

    cancel_event = asyncio.Event()
    pause_event = asyncio.Event()
    skip_event = asyncio.Event()
    debate_stopped = False

    async def listen_for_controls():
        nonlocal debate_stopped
        try:
            while True:
                msg = await websocket.receive_json()
                action = msg.get("action", "")
                if action == "pause":
                    pause_event.set()
                    await websocket.send_json({"type": "debate_paused"})
                elif action == "resume":
                    pause_event.clear()
                    await websocket.send_json({"type": "debate_resumed"})
                elif action == "stop":
                    debate_stopped = True
                    cancel_event.set()
                    pause_event.clear()
                    await websocket.send_json({"type": "debate_stopped"})
                    return
                elif action == "skip":
                    skip_event.set()
                    cancel_event.set()
        except (WebSocketDisconnect, Exception):
            debate_stopped = True
            cancel_event.set()

    try:
        config = await websocket.receive_json()
        topic = config.get("topic", "")
        domain = config.get("domain", "general")
        mode = config.get("mode", "ideate")
        num_phases = max(1, min(config.get("phases", 5), 7))
        num_debate_rounds = max(1, min(config.get("rounds", 8), 20))

        active_agents = AGENTS[:]

        await websocket.send_json({
            "type": "status",
            "message": f"Starting {'debate' if mode == 'debate' else 'ideation'} on: {topic}",
        })

        # Build phase map for frontend
        if mode == "debate":
            total_rounds_to_send = num_debate_rounds
            phase_map = {}
            for i in range(1, num_debate_rounds + 1):
                phase_map[str(i)] = f"R{i}"
        else:
            total_rounds_to_send = 6
            phase_map = {str(i): IDEATION_PHASES[i]["name"] for i in range(1, 7)}

        config_msg = {
            "type": "agents_config",
            "mode": mode,
            "agents": [
                {
                    "id": a["id"],
                    "name": a["name"],
                    "emoji": a["emoji"],
                    "color": a["color"],
                    "model": a.get("model", ""),
                    "debate_stance": a.get("debate_stance", "WILDCARD"),
                }
                for a in active_agents
            ],
            "total_phases": total_rounds_to_send,
            "phases": phase_map,
        }
        if mode != "debate":
            config_msg["round_agents"] = {str(k): v for k, v in ROUND_AGENT_MAP.items()}

        await websocket.send_json(config_msg)

        listener_task = asyncio.create_task(listen_for_controls())

        if mode == "debate":
            # ── Debate Mode Loop ──────────────────────────────────
            all_debate_history: list[tuple[str, str]] = []
            all_debate_transcript: list[tuple[str, str, str]] = []  # (name, stance, text)
            prev_speaker_name = ""
            prev_speaker_text = ""

            for round_num in range(1, num_debate_rounds + 1):
                if debate_stopped:
                    break

                while pause_event.is_set() and not debate_stopped:
                    await asyncio.sleep(0.2)

                if debate_stopped:
                    break

                await websocket.send_json({
                    "type": "round_start",
                    "round": round_num,
                    "total": num_debate_rounds,
                    "phase": f"R{round_num}",
                })

                for agent in active_agents:
                    if debate_stopped:
                        break

                    while pause_event.is_set() and not debate_stopped:
                        await asyncio.sleep(0.2)

                    if debate_stopped:
                        break

                    cancel_event.clear()
                    skip_event.clear()

                    await websocket.send_json({
                        "type": "agent_start",
                        "agent_id": agent["id"],
                        "agent_name": agent["name"],
                        "round": round_num,
                        "phase": f"R{round_num}",
                    })

                    system_prompt, user_prompt = build_debate_prompt(
                        agent, topic, domain,
                        round_num, num_debate_rounds,
                        prev_speaker_name, prev_speaker_text,
                        all_debate_history,
                    )

                    agent_temp = agent.get("temperature", 1.0)
                    cfg = AGENT_CFG.get(agent["id"], DEFAULT_AGENT_CFG)

                    response = await stream_ollama(
                        agent["model"],
                        user_prompt,
                        websocket,
                        agent["id"],
                        cancel_event,
                        system_prompt=system_prompt,
                        temperature=agent_temp,
                        num_predict=cfg["num_predict"],
                        num_ctx=cfg["num_ctx"],
                    )

                    skipped = skip_event.is_set()
                    stance = agent.get("debate_stance", "WILDCARD")

                    all_debate_history.append((agent["name"], response))
                    all_debate_transcript.append((agent["name"], stance, response))

                    prev_speaker_name = agent["name"]
                    prev_speaker_text = response

                    await websocket.send_json({
                        "type": "agent_done",
                        "agent_id": agent["id"],
                        "round": round_num,
                        "phase": f"R{round_num}",
                        "skipped": skipped,
                    })

                    await asyncio.sleep(0.3)

                if not debate_stopped:
                    await websocket.send_json({
                        "type": "round_end",
                        "round": round_num,
                    })

            # ── Verdict ───────────────────────────────────────────
            if not debate_stopped and all_debate_transcript:
                await websocket.send_json({
                    "type": "verdict_start",
                    "message": "The judge is deliberating...",
                })

                cancel_event.clear()
                verdict = await generate_verdict(
                    topic, all_debate_transcript, websocket, cancel_event,
                )

                await websocket.send_json({
                    "type": "verdict",
                    "text": verdict,
                })

            if not debate_stopped:
                await websocket.send_json({"type": "debate_complete"})

        else:
            # ── 6-Phase Directed Ideation Pipeline ────────────────────
            all_responses: dict[tuple[str, int], str] = {}

            for phase_num in range(1, 7):
                if debate_stopped:
                    break

                while pause_event.is_set() and not debate_stopped:
                    await asyncio.sleep(0.2)

                if debate_stopped:
                    break

                phase_cfg = IDEATION_PHASES.get(phase_num, IDEATION_PHASES[6])
                round_agent_ids = ROUND_AGENT_MAP.get(phase_num, [a["id"] for a in active_agents])
                round_agents = [a for a in active_agents if a["id"] in round_agent_ids]

                await websocket.send_json({
                    "type": "round_start",
                    "round": phase_num,
                    "total": 6,
                    "phase": phase_cfg["name"],
                    "active_agents": [a["id"] for a in round_agents],
                })

                for agent in round_agents:
                    if debate_stopped:
                        break

                    while pause_event.is_set() and not debate_stopped:
                        await asyncio.sleep(0.2)

                    if debate_stopped:
                        break

                    cancel_event.clear()
                    skip_event.clear()

                    await websocket.send_json({
                        "type": "agent_start",
                        "agent_id": agent["id"],
                        "agent_name": agent["name"],
                        "round": phase_num,
                        "phase": phase_cfg["name"],
                    })

                    system_prompt, user_prompt = build_ideation_prompt(
                        phase_num, agent, topic, domain, all_responses
                    )

                    agent_temp = agent.get("temperature", 1.0)
                    agent_cfg = AGENT_CFG.get(agent["id"], DEFAULT_AGENT_CFG)

                    response = await stream_ollama(
                        agent["model"],
                        user_prompt,
                        websocket,
                        agent["id"],
                        cancel_event,
                        system_prompt=system_prompt,
                        temperature=agent_temp,
                        num_predict=agent_cfg["num_predict"],
                        num_ctx=phase_cfg["num_ctx"],
                    )

                    skipped = skip_event.is_set()
                    all_responses[(agent["id"], phase_num)] = response

                    await websocket.send_json({
                        "type": "agent_done",
                        "agent_id": agent["id"],
                        "round": phase_num,
                        "phase": phase_cfg["name"],
                        "skipped": skipped,
                    })

                    await asyncio.sleep(0.3)

                if not debate_stopped:
                    await websocket.send_json({
                        "type": "round_end",
                        "round": phase_num,
                    })

            # ── Ideation Verdict ──────────────────────────────────
            if not debate_stopped and all_responses:
                await websocket.send_json({
                    "type": "verdict_start",
                    "message": "The venture analyst is evaluating...",
                })

                cancel_event.clear()
                verdict = await generate_ideation_verdict(
                    topic, domain, all_responses, websocket, cancel_event,
                )

                await websocket.send_json({
                    "type": "verdict",
                    "text": verdict,
                })

            if not debate_stopped:
                await websocket.send_json({"type": "debate_complete"})

        listener_task.cancel()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


# ── Transcript Storage ────────────────────────────────────────────────

TRANSCRIPTS_DIR.mkdir(exist_ok=True)


class TranscriptPayload(BaseModel):
    topic: str
    domain: str
    mode: str
    rounds: int
    agents: list[dict]
    entries: list[dict]
    verdict: Optional[str] = None
    timestamp: Optional[float] = None


@app.post("/api/transcript/save")
async def save_transcript(payload: TranscriptPayload):
    tid = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    data = payload.dict()
    data["id"] = tid
    data["timestamp"] = data.get("timestamp") or time.time()
    fpath = TRANSCRIPTS_DIR / f"{tid}.json"
    fpath.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return {"ok": True, "id": tid}


@app.get("/api/transcripts")
async def list_transcripts():
    results = []
    for f in sorted(TRANSCRIPTS_DIR.glob("*.json"), reverse=True):
        try:
            d = json.loads(f.read_text())
            results.append({
                "id": d.get("id", f.stem),
                "topic": d.get("topic", ""),
                "mode": d.get("mode", ""),
                "rounds": d.get("rounds", 0),
                "timestamp": d.get("timestamp", 0),
            })
        except Exception:
            pass
    return results


@app.delete("/api/transcripts/{tid}")
async def delete_transcript(tid: str):
    fpath = TRANSCRIPTS_DIR / f"{tid}.json"
    if fpath.exists():
        fpath.unlink()
        return {"ok": True}
    return JSONResponse(status_code=404, content={"error": "Not found"})


# ── Serve UI ──────────────────────────────────────────────────────────

@app.get("/")
async def get_ui():
    html_path = Path(__file__).parent / "index.html"
    return HTMLResponse(html_path.read_text())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765, reload=False)
