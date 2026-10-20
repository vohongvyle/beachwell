"""Thin Gemini client (REST, no SDK) plus deterministic offline fallbacks.

Online mode (GEMINI_API_KEY set):
  * generate_json() calls the configured LLM_MODEL with JSON output.
  * embed() calls EMBEDDING_MODEL with a fixed output dimension.
Offline mode (no key, or BEACHWELL_OFFLINE=1):
  * generate_json() returns None, and every agent falls back to its rule-based path.
  * embed() uses a hashed bag-of-words vector, so semantic search still works
    (less well) and every result is reproducible for tests and evaluation.

Every call is logged to the `llm_calls` table (prompt name, latency, success) so the
Phase 2 report can document the prompt/API workflow, as the course requires.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any

import numpy as np
import requests

from .config import get_settings

log = logging.getLogger("beachwell.llm")
API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
_call_log: list[dict[str, Any]] = []


def mode() -> str:
    return "gemini" if get_settings().online else "offline"


def recent_calls(limit: int = 50) -> list[dict[str, Any]]:
    return _call_log[-limit:]


def _record(kind: str, name: str, started: float, ok: bool, detail: str = "") -> None:
    _call_log.append(
        {"kind": kind, "name": name, "ms": round((time.time() - started) * 1000), "ok": ok, "detail": detail[:200]}
    )
    del _call_log[:-500]


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    return re.sub(r"\s*```$", "", text)


def generate_json(prompt: str, name: str, temperature: float = 0.2, timeout: float = 30.0) -> Any | None:
    """Ask Gemini for a JSON answer. Returns parsed JSON, or None offline / on any failure."""
    s = get_settings()
    if not s.online:
        return None
    started = time.time()
    try:
        resp = requests.post(
            f"{API_ROOT}/models/{s.llm_model}:generateContent",
            headers={"x-goog-api-key": s.gemini_api_key, "Content-Type": "application/json"},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        result = json.loads(_strip_fences(text))
        _record("generate", name, started, True)
        return result
    except Exception as exc:  # network, quota, malformed JSON: fall back, never crash a request
        log.warning("Gemini call %s failed: %s", name, exc)
        _record("generate", name, started, False, str(exc))
        return None


# ---------------------------------------------------------------- embeddings

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = set(
    "a an the and or of to in on for with at by from is are be i me my we our you your it this that as "
    "but not so if into about want need like really just some more get very".split()
)
# Small hand-written synonym map so the offline embedding can bridge everyday words
# ("move", "chill") to the vocabulary event descriptions use. Gemini embeddings do
# this far better; the map only keeps offline mode usable.
SYNONYMS = {
    "move": ["exercise", "fitness", "active"],
    "workout": ["exercise", "fitness", "gym"],
    "gym": ["fitness", "exercise"],
    "run": ["running", "exercise", "outdoor"],
    "chill": ["relax", "calm"],
    "relax": ["calm", "stress", "relief"],
    "calm": ["relax", "mindfulness", "quiet"],
    "stressed": ["stress", "relief", "relax"],
    "anxious": ["anxiety", "stress", "calm"],
    "anxiety": ["stress", "calm", "mindfulness"],
    "meditate": ["mindfulness", "meditation", "calm"],
    "meditation": ["mindfulness", "calm"],
    "art": ["craft", "creative", "painting"],
    "crafts": ["craft", "creative", "art"],
    "draw": ["art", "creative"],
    "dog": ["dogs", "puppies", "animals"],
    "dogs": ["puppies", "animals"],
    "puppies": ["dogs", "animals"],
    "food": ["snacks", "meal", "free"],
    "hungry": ["food", "meal", "snacks"],
    "friends": ["social", "community", "meet"],
    "lonely": ["social", "community", "connect", "meet"],
    "people": ["social", "community"],
    "music": ["concert", "sound", "jazz"],
    "outdoors": ["outdoor", "nature", "hike"],
    "nature": ["outdoor", "garden", "hike"],
    "study": ["studying", "focus", "academic"],
    "focus": ["study", "productivity"],
    "sleep": ["rest", "nap", "tired"],
    "tired": ["rest", "nap", "sleep"],
    "games": ["game", "play", "fun"],
    "quiet": ["calm", "quiet", "small"],
    "dance": ["dancing", "music", "active"],
    "yoga": ["stretch", "mindfulness", "fitness"],
    "swim": ["pool", "aquatics", "exercise"],
    "money": ["financial", "budget"],
    "talk": ["counseling", "support", "group"],
    "support": ["counseling", "group", "peer"],
}


def tokens(text: str) -> list[str]:
    toks = [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP and len(t) > 1]
    out: list[str] = []
    for t in toks:
        out.append(t)
        if t.endswith("s") and len(t) > 3:
            out.append(t[:-1])
        out.extend(SYNONYMS.get(t, []))
    return out


def _hash_embed(text: str, dim: int) -> np.ndarray:
    vec = np.zeros(dim, dtype=np.float32)
    for tok in tokens(text):
        h = int.from_bytes(hashlib.md5(tok.encode()).digest()[:8], "little")
        vec[h % dim] += 1.0 if (h >> 63) == 0 else -1.0
    # sublinear term weighting, then L2-normalise
    vec = np.sign(vec) * np.log1p(np.abs(vec))
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


_embed_cache: dict[tuple[str, str], np.ndarray] = {}


def embed(texts: list[str]) -> np.ndarray:
    """Embed texts to unit vectors (n x dim). Uses Gemini online, hashing offline."""
    s = get_settings()
    model = s.embedding_model if s.online else "offline-hash"
    out: list[np.ndarray | None] = [_embed_cache.get((model, t)) for t in texts]
    missing = [i for i, v in enumerate(out) if v is None]
    if missing and s.online:
        started = time.time()
        try:
            resp = requests.post(
                f"{API_ROOT}/models/{s.embedding_model}:batchEmbedContents",
                headers={"x-goog-api-key": s.gemini_api_key, "Content-Type": "application/json"},
                json={
                    "requests": [
                        {
                            "model": f"models/{s.embedding_model}",
                            "content": {"parts": [{"text": texts[i]}]},
                            "outputDimensionality": s.embedding_dim,
                        }
                        for i in missing
                    ]
                },
                timeout=30,
            )
            resp.raise_for_status()
            for i, emb in zip(missing, resp.json()["embeddings"]):
                v = np.asarray(emb["values"], dtype=np.float32)
                v = v / (np.linalg.norm(v) or 1.0)  # truncated-dimension outputs need re-normalising
                out[i] = v
                _embed_cache[(model, texts[i])] = v
            _record("embed", f"batch:{len(missing)}", started, True)
        except Exception as exc:
            # Never mix vector spaces in one call: fall back to offline for all texts.
            log.warning("Gemini embedding failed, using offline vectors: %s", exc)
            _record("embed", f"batch:{len(missing)}", started, False, str(exc))
            out = [None] * len(texts)
    for i, v in enumerate(out):
        if v is None:
            v = _hash_embed(texts[i], s.embedding_dim)
            _embed_cache[("offline-hash", texts[i])] = v
            out[i] = v
    return np.vstack(out) if out else np.zeros((0, s.embedding_dim), dtype=np.float32)
