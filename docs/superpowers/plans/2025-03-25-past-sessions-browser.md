# Past Sessions Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users open a "Past Sessions" modal from the header, browse saved transcripts (already stored under `transcripts/`), open one to read the full session, and delete entries — reusing existing list/delete APIs and adding a single GET endpoint for full payload.

**Architecture:** FastAPI already persists `POST /api/transcript/save` as `{tid}.json` and exposes `GET /api/transcripts` (metadata only) and `DELETE /api/transcripts/{tid}`. Add `GET /api/transcripts/{tid}` with strict ID validation to return the saved JSON. The SPA in `index.html` adds a second modal (same `.modal-overlay` pattern as Agent Manager) that lists rows from `GET /api/transcripts`, loads detail on selection, and renders entries with the same visual language as `#synthesisPanel` (colored left border, phase headers) using the `entries` array shape from `buildTranscriptData()` in `index.html`.

**Tech Stack:** Python 3, FastAPI, Pydantic, vanilla JS (no build), JSON files in `transcripts/`. Optional: `pytest` + `starlette.testclient` for API regression tests (not currently in `start.sh`).

---

## File structure (create / modify)

| Path | Responsibility |
|------|----------------|
| `server.py` | Add `GET /api/transcripts/{tid}` with path-safe `tid` validation; return 404 JSON on missing file. |
| `index.html` | Header button, modal markup, CSS for list/detail, JS: `openPastSessions`, `loadPastSessionsList`, `loadPastSessionDetail`, `deletePastSession`, `renderSavedSessionReadonly` (or inline). |
| `tests/test_transcripts_api.py` (create) | TestClient: GET 200 for valid file, GET 404 for missing, GET 400 for invalid tid shape, DELETE still works. |
| `requirements-dev.txt` (create, optional) | `pytest` only — for local dev; do not wire into `start.sh` unless you want CI. |

---

### Task 1: Backend — GET transcript by id

**Files:**
- Modify: `server.py` — append after `list_transcripts` (~1270–1286), before `delete_transcript`
- Test: `tests/test_transcripts_api.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_transcripts_api.py`:

```python
import json

import pytest
from starlette.testclient import TestClient

import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "TRANSCRIPTS_DIR", tmp_path)
    return TestClient(server.app)


def test_get_transcript_returns_full_json(client, tmp_path):
    tid = "1234567890_abcdef"
    data = {
        "id": tid,
        "topic": "Test topic",
        "domain": "crypto",
        "mode": "debate",
        "rounds": 4,
        "agents": [],
        "entries": [{"round": 1, "phase": "OPENING", "agent_name": "A", "text": "hello"}],
        "timestamp": 1.0,
    }
    (tmp_path / f"{tid}.json").write_text(json.dumps(data), encoding="utf-8")
    r = client.get(f"/api/transcripts/{tid}")
    assert r.status_code == 200
    assert r.json()["topic"] == "Test topic"


def test_get_transcript_404(client):
    r = client.get("/api/transcripts/9999999999_ffffff")
    assert r.status_code == 404


def test_get_transcript_rejects_bad_tid(client):
    r = client.get("/api/transcripts/../../../etc/passwd")
    assert r.status_code == 404


def test_get_transcript_rejects_malformed_tid(client):
    r = client.get("/api/transcripts/not-a-valid-id")
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/ebu/Desktop/Projects/AI Debate" && pip install pytest -q && pytest tests/test_transcripts_api.py -v`

Expected: FAIL (import or 404 on all routes / endpoint missing).

- [ ] **Step 3: Implement GET handler + validation**

In `server.py`, add after imports at module level (near other constants):

```python
_TRANSCRIPT_ID_RE = re.compile(r"^\d+_[a-f0-9]{6}$")
```

Add route between `list_transcripts` and `delete_transcript`:

```python
@app.get("/api/transcripts/{tid}")
async def get_transcript(tid: str):
    if not _TRANSCRIPT_ID_RE.match(tid):
        return JSONResponse(status_code=404, content={"error": "Not found"})
    fpath = TRANSCRIPTS_DIR / f"{tid}.json"
    if not fpath.is_file():
        return JSONResponse(status_code=404, content={"error": "Not found"})
    try:
        return json.loads(fpath.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"error": "Invalid transcript file"})
```

Ensure `import re` exists at top of `server.py` (add if missing).

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_transcripts_api.py -v`

Expected: PASS on all tests.

- [ ] **Step 5: Manual smoke with curl**

With server running and at least one saved transcript in `transcripts/`:

Run: `curl -s "http://localhost:8765/api/transcripts/<tid_from_filename>" | head -c 200`

Expected: JSON starting with `{"id":`

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_transcripts_api.py
git commit -m "feat(api): add GET /api/transcripts/{tid} for full transcript payload"
```

---

### Task 2: Frontend — Past Sessions modal (list + detail + delete)

**Files:**
- Modify: `index.html` — CSS block (~457+), header `.header-actions` (~948), new modal HTML after `agentModal` block (~1057+), script section

- [ ] **Step 1: Add header control**

In `index.html`, inside `.header-actions`, next to `Manage Agents`:

```html
<button type="button" class="btn-agents" onclick="openPastSessions()">Past Sessions</button>
```

- [ ] **Step 2: Add modal skeleton (mirror agent modal)**

After the closing `</div>` of `#agentModal` overlay, add:

```html
<div class="modal-overlay" id="pastSessionsModal">
  <div class="modal">
    <div class="modal-header">
      <h2>Saved sessions</h2>
      <button type="button" class="modal-close" onclick="closePastSessions()">&times;</button>
    </div>
    <div class="modal-body">
      <div id="pastSessionsList" class="past-sessions-list"></div>
      <div id="pastSessionsDetail" class="past-sessions-detail" style="display:none"></div>
    </div>
    <div class="modal-footer">
      <button type="button" class="btn-secondary" onclick="pastSessionsBack()" id="pastSessionsBackBtn" style="display:none">Back to list</button>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add minimal CSS**

Scoped classes: `.past-sessions-list` (scrollable max-height), `.past-session-row` (flex, border-bottom), `.past-sessions-detail .synth-entry` reuse or duplicate synthesis styles for readonly blocks.

- [ ] **Step 4: Implement JS functions**

Add functions (place near other modal helpers ~1734):

```javascript
async function openPastSessions() {
  document.getElementById('pastSessionsModal').classList.add('open');
  document.getElementById('pastSessionsDetail').style.display = 'none';
  document.getElementById('pastSessionsList').style.display = 'block';
  document.getElementById('pastSessionsBackBtn').style.display = 'none';
  await loadPastSessionsList();
}

function closePastSessions() {
  document.getElementById('pastSessionsModal').classList.remove('open');
}

async function loadPastSessionsList() {
  const el = document.getElementById('pastSessionsList');
  el.innerHTML = '<p class="muted">Loading…</p>';
  try {
    const r = await fetch('/api/transcripts');
    if (!r.ok) throw new Error('list failed');
    const rows = await r.json();
    if (!rows.length) {
      el.innerHTML = '<p class="muted">No saved sessions yet. Save from the banner after a run.</p>';
      return;
    }
    el.innerHTML = rows.map(row => {
      const d = new Date((row.timestamp || 0) * 1000);
      return `<div class="past-session-row" data-id="${row.id}">
        <div><strong>${escapeHtml(row.topic || 'Untitled')}</strong>
          <span class="muted">${row.mode || ''} · ${row.rounds || 0} rounds</span></div>
        <div class="muted">${d.toLocaleString()}</div>
        <button type="button" class="btn-small" onclick="event.stopPropagation(); deletePastSession('${row.id}')">Delete</button>
      </div>`;
    }).join('');
    el.querySelectorAll('.past-session-row').forEach(row => {
      row.addEventListener('click', () => openPastSessionDetail(row.dataset.id));
    });
  } catch (e) {
    el.innerHTML = '<p class="muted">Could not load sessions.</p>';
  }
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

async function openPastSessionDetail(tid) {
  const detail = document.getElementById('pastSessionsDetail');
  const list = document.getElementById('pastSessionsList');
  detail.style.display = 'block';
  list.style.display = 'none';
  document.getElementById('pastSessionsBackBtn').style.display = 'inline-block';
  detail.innerHTML = '<p class="muted">Loading…</p>';
  try {
    const r = await fetch('/api/transcripts/' + encodeURIComponent(tid));
    if (!r.ok) throw new Error('load failed');
    const data = await r.json();
    renderSavedSessionDetail(data);
  } catch (e) {
    detail.innerHTML = '<p class="muted">Could not load session.</p>';
  }
}

function pastSessionsBack() {
  document.getElementById('pastSessionsDetail').style.display = 'none';
  document.getElementById('pastSessionsList').style.display = 'block';
  document.getElementById('pastSessionsBackBtn').style.display = 'none';
  loadPastSessionsList();
}

async function deletePastSession(tid) {
  if (!confirm('Delete this saved session?')) return;
  try {
    const r = await fetch('/api/transcripts/' + encodeURIComponent(tid), { method: 'DELETE' });
    if (r.ok) {
      showToast('Deleted', 'success');
      await loadPastSessionsList();
    } else {
      showToast('Delete failed', 'error');
    }
  } catch (e) {
    showToast('Delete failed', 'error');
  }
}

function renderSavedSessionDetail(data) {
  const detail = document.getElementById('pastSessionsDetail');
  const modeLabel = data.mode === 'debate' ? '⚔️ Debate' : '💡 Ideation';
  let html = `<h3 class="past-detail-title">${escapeHtml(data.topic || '')}</h3>
    <p class="muted">${modeLabel} · ${escapeHtml(data.domain || '')} · ${data.rounds || 0} rounds</p>`;
  const entries = data.entries || [];
  let lastRound = null;
  entries.forEach(e => {
    if (e.round !== lastRound) {
      lastRound = e.round;
      html += `<div class="synth-round-divider"><span class="synth-round-num">Round ${e.round}</span><span class="synth-mode-badge">${escapeHtml(e.phase || '')}</span></div>`;
    }
    const color = (data.agents || []).find(a => a.id === e.agent_id)?.color || '#888';
    html += `<div class="synth-entry" style="border-left-color:${color}"><div class="synth-entry-header">
      <span>${e.agent_emoji || ''}</span> <span style="color:${color}">${escapeHtml(e.agent_name || '')}</span>
      ${e.stance ? `<span class="stance-badge">${escapeHtml(e.stance)}</span>` : ''}
  </div><div class="synth-entry-text">${escapeHtml(e.text || '').replace(/\n/g, '<br>')}</div></div>`;
  });
  if (data.verdict) {
    html += `<div class="synth-round-divider"><span class="synth-round-num">Verdict</span></div>`;
    html += `<div class="synth-entry" style="border-left-color:var(--gold)"><div class="synth-entry-text">${escapeHtml(data.verdict).replace(/\n/g, '<br>')}</div></div>`;
  }
  detail.innerHTML = html;
}
```

Adjust `escapeHtml` if you already have a similar helper — DRY.

- [ ] **Step 5: Manual verification**

1. `./start.sh`, open http://localhost:8765
2. Click **Past Sessions** → list loads (or empty message)
3. Run a short session, **Save to Server**, reopen modal → row appears
4. Click row → detail matches saved content; **Back** returns to list
5. **Delete** → row removed; file gone from `transcripts/`

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "feat(ui): Past Sessions modal to browse and delete saved transcripts"
```

---

### Task 3: Documentation touch-up (optional)

**Files:**
- Modify: `progress/SYSTEM_CONTEXT.md` — section "Past Sessions browser"

- [ ] **Step 1:** Mark Past Sessions as implemented under Phase 5 / remove from "NOT Been Implemented" with one sentence pointing to the modal.

- [ ] **Step 2: Commit**

```bash
git add progress/SYSTEM_CONTEXT.md
git commit -m "docs: document Past Sessions browser"
```

---

## Notes

- **YAGNI:** No search/filter in v1; list is newest-first from server already.
- **Security:** Only transcript IDs matching the same pattern as `save_transcript` are accepted; no path traversal.
- **If this plan was the wrong feature:** Copy the header template and file-structure section, replace tasks with the spec you choose; keep paths in `server.py` / `index.html` accurate.

---

## Plan review

- **Spec:** `progress/SYSTEM_CONTEXT.md` (Phase 5 — Past Sessions browser).
- Reviewer loop: run `plan-document-reviewer` (per superpowers:writing-plans) if available; otherwise human review of this file.

---

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2025-03-25-past-sessions-browser.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using superpowers:executing-plans, batch execution with checkpoints.

**Which approach?**

If you want a **different feature** (e.g. dark/light theme, markdown rendering, fullscreen cards, custom domains), say which one and we can replace this plan with a new dated file using the same structure.
