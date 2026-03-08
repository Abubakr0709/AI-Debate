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

DEFAULT_AGENTS = [
    {
        "id": "analyst",
        "name": "The Analyst",
        "emoji": "📊",
        "model": "huihui_ai/deepseek-r1-abliterated:8b-llama-distill",
        "color": "#00d4ff",
        "persona": "You are The Analyst — cold, data-driven, quantitative. You think in numbers, probabilities, and edge cases. You distrust vague claims and always demand hard evidence: what does the data actually say? Give a substantive response of 5-8 sentences. Cite specific numbers, statistics, percentages, or historical data points when possible. Destroy vague claims with precision. Be direct and uncompromising."
    },
    {
        "id": "strategist",
        "name": "The Strategist",
        "emoji": "♟️",
        "model": "r1-wild:latest",
        "color": "#ff6b35",
        "persona": "You are The Strategist — you think in systems, long-term plays, and asymmetric advantages. You see patterns others miss and think 10 steps ahead. You are bold, confident, and unafraid of big claims. Give a substantive response of 5-8 sentences. Think through second and third-order consequences. Be specific about timelines, leverage points, and the decisive move others are missing."
    },
    {
        "id": "devil",
        "name": "Devil's Advocate",
        "emoji": "😈",
        "model": "huihui_ai/deepseek-r1-abliterated:8b-llama-distill",
        "color": "#ff3366",
        "persona": "You are The Devil's Advocate — your job is to destroy weak arguments. You challenge every assumption, find the fatal flaw, and expose what others are conveniently ignoring. You are provocative, sharp, and deliberately uncomfortable. Give a substantive response of 5-8 sentences. Name specific claims from other agents and dismantle them directly. One devastating argument beats five weak ones — go for the jugular."
    },
    {
        "id": "synthesizer",
        "name": "The Synthesizer",
        "emoji": "🔮",
        "model": "r1-wild:latest",
        "color": "#a855f7",
        "persona": "You are The Synthesizer — you listen to all perspectives and extract signal from noise. You find where agents genuinely agree, where they talk past each other, and what the actionable truth actually is. Give a substantive response of 5-8 sentences. Identify the strongest point from each agent, the core tension in the debate, and what a rational decision-maker should actually conclude and do next."
    },
    {
        "id": "tactician",
        "name": "The Tactician",
        "emoji": "🎯",
        "model": "mistral:7b",
        "color": "#00ff88",
        "persona": "You are The Tactician — you cut through theory to demand executable action. While others debate frameworks, you ask: what specific steps do we take this week, what tools do we use, and how do we measure success? Give a substantive response of 5-8 sentences. Name concrete tools, specific thresholds, measurable outcomes, and realistic timelines. Abstract advice is useless — give the actual playbook."
    },
    {
        "id": "wildcard",
        "name": "The Wildcard",
        "emoji": "🃏",
        "model": "llama3.2:3b",
        "color": "#ffd700",
        "persona": "You are The Wildcard — you think laterally and make unexpected connections that reframe the entire debate. You draw from psychology, evolutionary biology, game theory, military history, or whatever field nobody else thought to reference. Give a substantive response of 5-8 sentences. Challenge the conventional framing of the question itself. The most interesting insight is usually the one nobody considered."
    }
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


class AgentCreate(BaseModel):
    name: str
    emoji: str = "🤖"
    model: str
    color: str = "#888888"
    persona: str = "You are a helpful debater. Keep responses to 3-4 sharp sentences."


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
    new_id = agent.name.lower().replace(" ", "_").replace("'", "")
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


# ── Think-tag filtering ──────────────────────────────────────────────

THINK_OPEN = re.compile(r"<think>", re.IGNORECASE)
THINK_CLOSE = re.compile(r"</think>", re.IGNORECASE)


async def stream_ollama(model: str, prompt: str, ws: WebSocket, agent_id: str,
                        cancel_event: asyncio.Event):
    """Stream from Ollama, filtering <think> blocks server-side."""
    full_response = ""
    clean_response = ""
    inside_think = False
    think_buffer = ""

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream("POST", OLLAMA_URL, json={
                "model": model,
                "prompt": prompt,
                "stream": True,
                "options": {"temperature": 1.0, "num_predict": 2500, "num_ctx": 8192}
            }) as response:
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
                                            "token": emit
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
                                            "token": safe
                                        })
                                        think_buffer = think_buffer[len(safe):]
                                    break

                        if data.get("done"):
                            break
                    except json.JSONDecodeError:
                        pass

        if think_buffer and not inside_think:
            clean_response += think_buffer
            await ws.send_json({
                "type": "token",
                "agent_id": agent_id,
                "token": think_buffer
            })

    except Exception as e:
        if not cancel_event.is_set():
            await ws.send_json({
                "type": "token",
                "agent_id": agent_id,
                "token": f"\n[Error: {str(e)}]"
            })
    return clean_response


# ── Prompt builders ───────────────────────────────────────────────────

def build_solo_prompt(agent: dict, topic: str, domain: str) -> str:
    domain_ctx = {
        "crypto": "The domain is cryptocurrency trading and bot strategy.",
        "military": "The domain is military technology and autonomous defense systems."
    }.get(domain, f"The domain is: {domain}.")
    return f"""{agent['persona']}

{domain_ctx}

Topic for debate: {topic}

Give your opening position on this topic. Be direct and distinctive."""


def build_response_prompt(agent: dict, topic: str, domain: str,
                          previous_round: list[tuple[str, str]]) -> str:
    domain_ctx = {
        "crypto": "The domain is cryptocurrency trading and bot strategy.",
        "military": "The domain is military technology and autonomous defense systems."
    }.get(domain, f"The domain is: {domain}.")

    history = "\n\n".join([
        f"{name} said: {msg}" for name, msg in previous_round if msg.strip()
    ])

    return f"""{agent['persona']}

{domain_ctx}

Topic: {topic}

What the other agents said:
{history}

Now respond directly to the other agents. Agree with what's right, destroy what's wrong, add what they missed. Be direct and mention specific agents by name."""


# ── Debate WebSocket with live controls ───────────────────────────────

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
        domain = config.get("domain", "crypto")
        num_rounds = config.get("rounds", 3)

        await websocket.send_json({"type": "status", "message": f"Starting debate on: {topic}"})
        await websocket.send_json({
            "type": "agents_config",
            "agents": [{"id": a["id"], "name": a["name"], "emoji": a["emoji"],
                        "color": a["color"], "model": a.get("model", "")} for a in AGENTS]
        })

        listener_task = asyncio.create_task(listen_for_controls())

        all_responses: list[tuple[str, str]] = []

        for round_num in range(1, num_rounds + 1):
            if debate_stopped:
                break

            while pause_event.is_set() and not debate_stopped:
                await asyncio.sleep(0.2)

            if debate_stopped:
                break

            await websocket.send_json({
                "type": "round_start",
                "round": round_num,
                "total": num_rounds,
                "mode": "solo" if round_num <= 2 else "debate"
            })

            round_responses: list[tuple[str, str]] = []

            for agent in AGENTS:
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
                    "round": round_num
                })

                if round_num <= 2:
                    prompt = build_solo_prompt(agent, topic, domain)
                else:
                    prompt = build_response_prompt(
                        agent, topic, domain,
                        all_responses[-len(AGENTS):]
                    )

                response = await stream_ollama(
                    agent["model"], prompt, websocket, agent["id"], cancel_event
                )

                skipped = skip_event.is_set()
                round_responses.append((agent["name"], response))

                await websocket.send_json({
                    "type": "agent_done",
                    "agent_id": agent["id"],
                    "round": round_num,
                    "skipped": skipped
                })

                await asyncio.sleep(0.3)

            all_responses.extend(round_responses)

            if not debate_stopped:
                await websocket.send_json({
                    "type": "round_end",
                    "round": round_num
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
