# ARENA — AI Debate System

4 local AI agents debate your crypto or military tech topics in real time.

## Setup

```bash
# 1. Make startup script executable
chmod +x start.sh

# 2. Make sure Ollama is running (should already be)
# Your models: r1-wild:latest + huihui_ai/deepseek-r1-abliterated:8b-llama-distill

# 3. Start the server
./start.sh

# 4. Open browser
open http://localhost:8765
```

## How it works

- **Rounds 1–2**: Each agent gives their own independent take (SOLO mode)
- **Rounds 3+**: Agents read each other's previous responses and argue directly (DEBATE mode)
- **Round tabs**: Click round tabs in each agent card to see their response per round

## Agents

| Agent | Personality | Model |
|---|---|---|
| 📊 The Analyst | Data-driven, skeptical | deepseek-r1-abliterated:8b |
| ♟️ The Strategist | Big-picture, bold | r1-wild:latest |
| 😈 Devil's Advocate | Challenges everything | deepseek-r1-abliterated:8b |
| 🔮 The Synthesizer | Finds the signal | r1-wild:latest |

## Adding more models later

Edit `server.py` → update `AGENTS` list with new model names.
Good additions: `mistral:7b`, `llama3.2:3b`, `phi3:mini`

## Topic ideas

**Crypto:**
- "What is the optimal risk-per-trade for a BTC scalping bot?"
- "Should we use sentiment analysis or pure price action for entries?"
- "How should the bot behave during high-volatility news events?"

**Military:**
- "How should autonomous drones decide when to abort a mission?"
- "What AI architecture is best for real-time threat detection?"
- "Should autonomous weapons systems require human confirmation to fire?"
