import asyncio
import json
import re
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

# ── Phase Configuration ───────────────────────────────────────────────

PHASES = {
    1: {"name": "DIVERGE",     "num_predict": 1200, "num_ctx": 4096},
    2: {"name": "CHALLENGE",   "num_predict": 1200, "num_ctx": 8192},
    3: {"name": "COMBINE",     "num_predict": 1200, "num_ctx": 8192},
    4: {"name": "STRESS-TEST", "num_predict": 1200, "num_ctx": 8192},
    5: {"name": "EXECUTE",     "num_predict": 1500, "num_ctx": 8192},
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


class AgentCreate(BaseModel):
    name: str
    emoji: str = "🤖"
    model: str
    color: str = "#888888"
    persona: str = "You are a creative problem solver. Be specific and actionable."
    temperature: float = 1.0


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

                        while think_buffer:
                            if inside_think:
                                close_match = THINK_CLOSE.search(think_buffer)
                                if close_match:
                                    inside_think = False
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


# ── Phase Prompt Builder ──────────────────────────────────────────────

def build_phase_prompt(
    phase: int,
    agent: dict,
    topic: str,
    domain: str,
    full_history: list[tuple[str, str]],
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for the given ideation phase."""

    domain_ctx = (
        f"The domain is: {domain}. "
        "Think about real companies, real markets, and real technology in this space."
    )

    history_text = ""
    if full_history:
        history_text = "\n\n".join(
            f"[{name}]: {msg}" for name, msg in full_history if msg.strip()
        )

    system_prompt = agent.get("persona", "You are a creative problem solver.")

    if phase == 1:  # ── DIVERGE ──
        user_prompt = (
            f"{domain_ctx}\n\n"
            f"Topic: {topic}\n\n"
            "BRAINSTORM PHASE — Generate exactly 3 specific, actionable ideas "
            "related to this topic. For each idea:\n"
            "• Give it a punchy one-line name\n"
            "• Explain the core mechanism — how does it make money or solve the problem?\n"
            "• Name one existing tool, technology, or market trend it leverages\n"
            "• Estimate the realistic revenue potential or impact\n\n"
            "Be specific and unconventional. The best ideas combine things nobody "
            "has connected yet. No generic advice — every idea must be something "
            "someone could start building this week."
        )

    elif phase == 2:  # ── CHALLENGE ──
        user_prompt = (
            f"{domain_ctx}\n\n"
            f"Topic: {topic}\n\n"
            f"IDEAS PROPOSED SO FAR:\n{history_text}\n\n"
            "CHALLENGE PHASE — Review every idea above. For each one:\n"
            "1. Name the specific flaw, fatal assumption, or market risk\n"
            "2. Propose a concrete fix, pivot, or mitigation that saves the core insight\n\n"
            "Then identify which single idea has the highest real-world potential "
            "and explain WHY — what makes it more viable than the others?\n"
            "Never just kill ideas — evolve them through pressure."
        )

    elif phase == 3:  # ── COMBINE ──
        user_prompt = (
            f"{domain_ctx}\n\n"
            f"Topic: {topic}\n\n"
            f"FULL DISCUSSION SO FAR:\n{history_text}\n\n"
            "COMBINATION PHASE — Create ONE powerful hybrid idea that fuses the "
            "strongest elements from at least 2 different proposals discussed above. "
            "Explain:\n"
            "• What specific elements you're combining and why they reinforce each other\n"
            "• The revenue model or value creation mechanism\n"
            "• What makes this combination non-obvious — why hasn't someone done this already?\n"
            "• One specific real-world example or analogy that validates this approach\n\n"
            "This must be a genuinely new concept, not just a feature list."
        )

    elif phase == 4:  # ── STRESS-TEST ──
        user_prompt = (
            f"{domain_ctx}\n\n"
            f"Topic: {topic}\n\n"
            f"FULL DISCUSSION SO FAR:\n{history_text}\n\n"
            "STRESS-TEST PHASE — Take the most promising idea from this discussion "
            "and pressure-test it:\n"
            "• Market size: How big is this opportunity? Name specific numbers or comparable markets.\n"
            "• Competition: Who is closest to doing this? What's your specific edge over them?\n"
            "• Feasibility: What does a minimum viable version require? Time, cost, skills, tools.\n"
            "• Unit economics: What does one customer/unit cost to acquire vs revenue generated?\n"
            "• Kill shot: What's the single most likely reason this fails, and how do you mitigate it?\n\n"
            "Be brutally honest but constructive. If it survives this test, it's worth building."
        )

    elif phase == 5:  # ── EXECUTE ──
        user_prompt = (
            f"{domain_ctx}\n\n"
            f"Topic: {topic}\n\n"
            f"FULL DISCUSSION SO FAR:\n{history_text}\n\n"
            "EXECUTION PHASE — Write a concrete action plan for the strongest idea "
            "from this discussion:\n"
            "• THIS WEEK: 3 specific actions to take, tools to set up, or research to complete\n"
            "• MONTH 1: First milestone, success metric, and estimated cost to reach it\n"
            "• MONTH 3: Scale trigger — what metric tells you this is working?\n"
            "• TOOLS & STACK: Name specific platforms, APIs, frameworks, or services to use\n"
            "• FIRST DOLLAR: How specifically does this make its first revenue?\n\n"
            "No abstract advice. Every sentence must be an action someone can take "
            "starting tomorrow."
        )

    else:  # ── Extra rounds beyond 5 ──
        user_prompt = (
            f"{domain_ctx}\n\n"
            f"Topic: {topic}\n\n"
            f"DISCUSSION SO FAR:\n{history_text}\n\n"
            "Continue building on the strongest ideas from this discussion. "
            "Add new angles, deeper analysis, or refined execution details. "
            "Be specific and actionable."
        )

    return system_prompt, user_prompt


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
        num_phases = max(1, min(config.get("phases", 5), 7))

        active_agents = AGENTS[:]

        await websocket.send_json({
            "type": "status",
            "message": f"Starting ideation on: {topic}",
        })

        # Build phase map for frontend
        phase_map = {}
        for i in range(1, num_phases + 1):
            if i in PHASES:
                phase_map[str(i)] = PHASES[i]["name"]
            else:
                phase_map[str(i)] = f"ROUND {i}"

        await websocket.send_json({
            "type": "agents_config",
            "agents": [
                {
                    "id": a["id"],
                    "name": a["name"],
                    "emoji": a["emoji"],
                    "color": a["color"],
                    "model": a.get("model", ""),
                }
                for a in active_agents
            ],
            "total_phases": num_phases,
            "phases": phase_map,
        })

        listener_task = asyncio.create_task(listen_for_controls())

        # ── 5-Phase Ideation Loop ─────────────────────────────────
        all_responses: list[tuple[str, str]] = []

        for phase_num in range(1, num_phases + 1):
            if debate_stopped:
                break

            while pause_event.is_set() and not debate_stopped:
                await asyncio.sleep(0.2)

            if debate_stopped:
                break

            phase_cfg = PHASES.get(phase_num, PHASES[5])

            await websocket.send_json({
                "type": "round_start",
                "round": phase_num,
                "total": num_phases,
                "phase": phase_cfg["name"],
            })

            round_responses: list[tuple[str, str]] = []

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
                    "round": phase_num,
                    "phase": phase_cfg["name"],
                })

                # Build prompts — full history passed for cumulative context
                system_prompt, user_prompt = build_phase_prompt(
                    phase_num, agent, topic, domain, all_responses
                )

                agent_temp = agent.get("temperature", 1.0)

                response = await stream_ollama(
                    agent["model"],
                    user_prompt,
                    websocket,
                    agent["id"],
                    cancel_event,
                    system_prompt=system_prompt,
                    temperature=agent_temp,
                    num_predict=phase_cfg["num_predict"],
                    num_ctx=phase_cfg["num_ctx"],
                )

                skipped = skip_event.is_set()
                round_responses.append((agent["name"], response))

                await websocket.send_json({
                    "type": "agent_done",
                    "agent_id": agent["id"],
                    "round": phase_num,
                    "phase": phase_cfg["name"],
                    "skipped": skipped,
                })

                await asyncio.sleep(0.3)

            all_responses.extend(round_responses)

            if not debate_stopped:
                await websocket.send_json({
                    "type": "round_end",
                    "round": phase_num,
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


# ── Serve UI ──────────────────────────────────────────────────────────

@app.get("/")
async def get_ui():
    html_path = Path(__file__).parent / "index.html"
    return HTMLResponse(html_path.read_text())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765, reload=False)
