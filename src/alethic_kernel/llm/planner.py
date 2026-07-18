from __future__ import annotations
import http.client, json, re, ssl
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

_DEFAULT_URL = "http://localhost:11434/v1/chat/completions"
_DEFAULT_MODEL = "qwen3:8b"

def _strip_think(text: str) -> str:
    """Remove <think>...</think> blocks from Qwen3 output."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first JSON object from text, handling markdown fences."""
    text = _strip_think(text)
    # try markdown code block first
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        try:
            result: Dict[str, Any] = json.loads(m.group(1))
            return result
        except json.JSONDecodeError:
            pass
    # try raw JSON
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            result = json.loads(m.group(0))
            return result
        except json.JSONDecodeError:
            pass
    return None

def chat(messages: list[Dict[str, str]], *,
         base_url: str = _DEFAULT_URL,
         model: str = _DEFAULT_MODEL,
         temperature: float = 0.3,
         max_tokens: int = 512,
         api_key: Optional[str] = None,
         reasoning_effort: Optional[str] = None) -> str:
    """Send chat completion request; return assistant message text."""
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if reasoning_effort is not None:
        payload["reasoning_effort"] = reasoning_effort
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if api_key is not None:
        headers["Authorization"] = f"Bearer {api_key}"
    parsed = urlparse(base_url)
    body = json.dumps(payload).encode()
    if parsed.scheme == "https":
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(
            parsed.hostname or "", parsed.port or 443,
            context=ssl.create_default_context(), timeout=120,
        )
    else:
        conn = http.client.HTTPConnection(
            parsed.hostname or "", parsed.port or 80, timeout=120,
        )
    try:
        conn.request("POST", parsed.path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        if resp.status != 200:
            raise RuntimeError(
                f"LLM API returned HTTP {resp.status}: {raw.decode('utf-8', errors='replace')[:500]}"
            )
        data = json.loads(raw)
    finally:
        conn.close()
    content: str = data["choices"][0]["message"]["content"]
    return content

# ── Belief proposal ──────────────────────────────────────────────────

_BELIEF_SYSTEM = """\
You are a planner in a governed decision system. Given percepts, decide whether to propose a belief.

IMPORTANT:
- Always propose the belief if the percept data exists — even if stale, conflicting, or low-confidence.
- A separate validator checks evidence quality. You do NOT enforce safety.
- Only decline if the percepts contain NO relevant data at all.

Respond with ONLY a JSON object.

Propose: {{"propose": true, "value": true, "depends_on": {depends_on}, "reasoning": "brief"}}
Decline: {{"propose": false, "reasoning": "why"}}"""

def propose_belief(percepts: Dict[str, Any], constraints: Dict[str, Any],
                   task_description: str = "",
                   belief_name: str = "refund_due",
                   percept_keys: Optional[List[str]] = None,
                   **kw: Any) -> Optional[Dict[str, Any]]:
    """Ask the LLM to propose a belief given percepts."""
    percept_keys = percept_keys or list(percepts.keys())
    system = _BELIEF_SYSTEM.format(depends_on=json.dumps(percept_keys))
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": (
            f"Task: {task_description}\n"
            f"Belief to evaluate: \"{belief_name}\"\n"
            f"Percepts: {json.dumps(percepts)}\n"
            f"Constraints: {json.dumps(constraints)}"
        )},
    ]
    raw = chat(messages, **kw)
    return _extract_json(raw)

# ── Plan proposal ────────────────────────────────────────────────────

_PLAN_SYSTEM = """\
You are a planner in a governed decision system. Propose an action plan.

Rules:
- Every step MUST include requires_beliefs with the beliefs it depends on.
- Set is_duplicate from the action context.
- A constraint validator checks the plan — propose honestly.

Respond with ONLY a JSON object.

Format: {{"steps": [{{"action": "issue_refund", "requires_beliefs": {requires_beliefs}, "is_duplicate": <bool>}}]}}
No action: {{"steps": []}}"""

def propose_plan(beliefs: Dict[str, Any], constraints: Dict[str, Any],
                 task_description: str = "",
                 action_context: Optional[Dict[str, Any]] = None,
                 required_beliefs: Optional[List[str]] = None,
                 **kw: Any) -> Optional[Dict[str, Any]]:
    """Ask the LLM to propose an action plan given committed beliefs."""
    action_context = action_context or {}
    required_beliefs = required_beliefs or list(beliefs.keys())
    system = _PLAN_SYSTEM.format(requires_beliefs=json.dumps(required_beliefs))
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": (
            f"Task: {task_description}\n"
            f"Committed beliefs: {json.dumps(beliefs)}\n"
            f"Constraints: {json.dumps(constraints)}\n"
            f"Action context: {json.dumps(action_context)}"
        )},
    ]
    raw = chat(messages, **kw)
    return _extract_json(raw)

# ── Action proposal ──────────────────────────────────────────────────

_ACTION_SYSTEM = """\
You are a planner in a governed decision system. Produce the concrete action payload.

Rules:
- Use the refund details and is_duplicate flag EXACTLY as provided.
- Copy requires_beliefs from the plan step.

Respond with ONLY a JSON object.

Format: {{"type": "issue_refund", "description": "...", "is_duplicate": <bool>, "requires_beliefs": [...]}}"""

def propose_action(plan_step: Dict[str, Any], message_text: str,
                   is_duplicate: bool,
                   action_metadata: Optional[Dict[str, Any]] = None,
                   **kw: Any) -> Optional[Dict[str, Any]]:
    """Ask the LLM to formulate the concrete action payload."""
    action_metadata = action_metadata or {}
    messages = [
        {"role": "system", "content": _ACTION_SYSTEM},
        {"role": "user", "content": (
            f"Plan step: {json.dumps(plan_step)}\n"
            f"Refund description: {message_text}\n"
            f"Is duplicate: {is_duplicate}\n"
            f"Metadata: {json.dumps(action_metadata)}"
        )},
    ]
    raw = chat(messages, **kw)
    return _extract_json(raw)
