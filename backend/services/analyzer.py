"""
Tag extraction pipeline — Phase 5 (algorithmic) + Phase 6 (LLM).

Pipeline order (per PRD §5.3):
  1. Profile wordlist fuzzy scan (rapidfuzz, threshold 85%)
  2. Global wordlist fuzzy scan
  3. LLM call (if analysis_method == "llm" and llm_enabled on profile)
  4. spaCy NLP fallback
  5. Flag needs_more=True if still < N (user fills the rest manually via frontend)

Tags are returned ordered by first_appearance_offset in the script.
"""
import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

import httpx
import spacy
from rapidfuzz import fuzz, process
from sqlalchemy.orm import Session

from db.models import AppSettings, GlobalTag, LLMProvider, NicheProfile, ProfileTag
from session_state import Tag

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 85
NLP_FUZZY_THRESHOLD = 80
LLM_TIMEOUT = 30

_nlp_model: spacy.language.Language | None = None


def _get_nlp() -> spacy.language.Language:
    global _nlp_model
    if _nlp_model is None:
        _nlp_model = spacy.load("en_core_web_sm")
    return _nlp_model


@dataclass
class TagExtractionResult:
    tags: list[Tag]
    count: int
    needed: int
    needs_more: bool
    method_used: list[str] = field(default_factory=list)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return text.lower().strip()


def _find_offset(script_lower: str, phrase: str) -> int:
    """Return char offset of `phrase` in script, or -1 if not found."""
    return script_lower.find(phrase.lower())


def _fuzzy_scan(
    script: str,
    wordlist: list[str],
    already_found: set[str],
    dedupe: bool,
    n_remaining: int,
) -> list[tuple[str, int, str]]:
    """
    Scan script for words in wordlist using fuzzy matching.
    Returns list of (word, offset, source_label) up to n_remaining slots.
    """
    script_lower = script.lower()
    # Split script into words for token-level fuzzy matching
    tokens = re.findall(r"\b\w[\w\s]*?\b", script_lower)

    found: list[tuple[str, int, str]] = []
    seen_words: set[str] = set(already_found)

    for word in wordlist:
        if len(found) >= n_remaining:
            break
        word_lower = _normalize(word)
        if dedupe and word_lower in seen_words:
            continue

        # Try exact substring match first (fast path)
        idx = script_lower.find(word_lower)
        if idx != -1:
            if not dedupe or word_lower not in seen_words:
                found.append((word, idx, ""))
                seen_words.add(word_lower)
            continue

        # Fuzzy match against script tokens
        for token in tokens:
            score = fuzz.token_set_ratio(word_lower, token)
            if score >= FUZZY_THRESHOLD:
                idx = _find_offset(script_lower, token)
                if not dedupe or word_lower not in seen_words:
                    found.append((word, max(idx, 0), ""))
                    seen_words.add(word_lower)
                break

    return found


# ── LLM cascade ───────────────────────────────────────────────────────────────

async def _call_llm_cascade(prompt: str, providers: list[LLMProvider]) -> str | None:
    for provider in sorted(providers, key=lambda p: p.priority):
        if not provider.enabled:
            continue
        try:
            result = await _call_provider(provider, prompt)
            if result:
                return result
        except Exception as exc:
            logger.warning("LLM provider '%s' failed: %s", provider.name, exc)
    return None


async def _call_provider(provider: LLMProvider, prompt: str) -> str | None:
    headers = {"Content-Type": "application/json"}
    timeout = LLM_TIMEOUT

    if provider.provider_type == "openai":
        headers["Authorization"] = f"Bearer {provider.api_key}"
        payload = {
            "model": provider.model or "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers=headers,
            )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    elif provider.provider_type == "anthropic":
        headers["x-api-key"] = provider.api_key or ""
        headers["anthropic-version"] = "2023-06-01"
        payload = {
            "model": provider.model or "claude-haiku-4-5-20251001",
            "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt}],
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
            )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]

    elif provider.provider_type == "gemini":
        model = provider.model or "gemini-1.5-flash"
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            f"?key={provider.api_key}"
        )
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    elif provider.provider_type == "ollama":
        base = (provider.base_url or "http://localhost:11434").rstrip("/")
        payload = {
            "model": provider.model or "llama3",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{base}/api/chat", json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    elif provider.provider_type == "custom":
        base = (provider.base_url or "").rstrip("/")
        if provider.api_key:
            headers["Authorization"] = f"Bearer {provider.api_key}"
        payload = {
            "model": provider.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{base}/v1/chat", json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    return None


def _build_llm_prompt(
    script: str,
    n: int,
    profile_tags: list[str],
    global_tags: list[str],
) -> str:
    return f"""[TASK]
You are a B-roll tag extractor. Given a video script, extract exactly {n} searchable tags to find relevant B-roll footage. Tags should be concrete, visual nouns or noun phrases (things that can be photographed or filmed).

[NICHE PROFILE WORD LIST]
{", ".join(profile_tags) if profile_tags else "(none)"}
(These are high-priority terms specific to this niche. Always include any of these that appear in the script before picking general tags.)

[GLOBAL SUPPLEMENTARY WORD LIST]
{", ".join(global_tags) if global_tags else "(none)"}
(Use these as secondary reference to fill remaining slots after profile tags are exhausted.)

[SCRIPT]
{script}

[OUTPUT FORMAT]
Return exactly a JSON array of {n} strings, ordered by first appearance in the script. Example:
["the emperor", "space marine", "chaos army", "warp storm", "ultramarines chapter"]

[CONSTRAINTS]
Return only the JSON array. No explanation. No preamble. No trailing questions. No markdown code fences."""


def _parse_llm_response(text: str, n: int) -> list[str]:
    """Extract JSON array from LLM response. Returns [] on parse failure."""
    text = text.strip()
    # Strip markdown fences if present despite the constraint
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        tags = json.loads(text)
        if isinstance(tags, list):
            return [str(t).strip() for t in tags[:n]]
    except json.JSONDecodeError:
        pass
    return []


# ── spaCy algorithmic fallback ────────────────────────────────────────────────

def _spacy_extract(
    script: str,
    n: int,
    profile_words: list[str],
    global_words: list[str],
    already_found: set[str],
) -> list[tuple[str, int]]:
    """
    Run spaCy NER + noun chunk extraction, score, dedupe, return top candidates.
    Returns list of (phrase, offset).
    """
    nlp = _get_nlp()
    doc = nlp(script)
    script_lower = script.lower()

    candidates: dict[str, dict] = {}  # lemma → {text, offset, score}

    def _add(text: str, offset: int, is_entity: bool, is_chunk: bool):
        lemma = nlp.vocab.strings[text.lower()] if text.lower() in nlp.vocab.strings else text.lower()
        key = text.lower()
        if key in candidates:
            return
        score = 0.0
        if any(fuzz.token_set_ratio(text.lower(), w.lower()) >= NLP_FUZZY_THRESHOLD for w in profile_words):
            score += 2
        elif any(fuzz.token_set_ratio(text.lower(), w.lower()) >= NLP_FUZZY_THRESHOLD for w in global_words):
            score += 1
        if is_entity:
            score += 1
        if is_chunk:
            score += 0.5
        candidates[key] = {"text": text, "offset": offset, "score": score}

    for ent in doc.ents:
        offset = _find_offset(script_lower, ent.text)
        _add(ent.text, max(offset, 0), is_entity=True, is_chunk=False)

    for chunk in doc.noun_chunks:
        offset = _find_offset(script_lower, chunk.text)
        _add(chunk.text, max(offset, 0), is_entity=False, is_chunk=True)

    # Filter out already-found words
    filtered = [v for k, v in candidates.items() if k not in already_found]
    # Sort: score DESC, offset ASC
    filtered.sort(key=lambda x: (-x["score"], x["offset"]))
    return [(c["text"], c["offset"]) for c in filtered[:n]]


# ── Main entry point ──────────────────────────────────────────────────────────

def extract_tags(
    script_text: str,
    profile: NicheProfile,
    n: int,
    db: Session,
    analysis_method: str | None = None,
    dedupe_override: bool | None = None,
) -> TagExtractionResult:
    """
    Synchronous wrapper called from the sessions router via asyncio.to_thread().
    The LLM call inside is run via asyncio.run() since we're in a thread.
    """
    # Pre-process
    script = re.sub(r"\s+", " ", script_text).strip()
    script_lower = script.lower()
    dedupe = dedupe_override if dedupe_override is not None else profile.dedupe_repeat_tags

    # Load wordlists
    profile_words = [t.word for t in db.query(ProfileTag).filter(ProfileTag.profile_id == profile.id).all()]
    global_words = [t.word for t in db.query(GlobalTag).all()]

    tags: list[Tag] = []
    seen_words: set[str] = set()
    method_used: list[str] = []

    def _add_tags(word_offset_pairs: list[tuple[str, int]], source: str):
        for word, offset in word_offset_pairs:
            if len(tags) >= n:
                break
            word_lower = word.lower()
            is_dup = word_lower in seen_words
            if dedupe and is_dup:
                continue
            tags.append(Tag(
                word=word,
                source=source,
                occurrence_index=offset,
                is_duplicate=is_dup,
            ))
            seen_words.add(word_lower)

    # Step 1: Profile wordlist fuzzy scan
    if profile_words:
        hits = _fuzzy_scan(script, profile_words, seen_words.copy(), dedupe, n - len(tags))
        _add_tags([(w, off) for w, off, _ in hits], "profile_wordlist")
        if hits:
            method_used.append("profile_wordlist")

    # Step 2: Global wordlist fuzzy scan
    if len(tags) < n and global_words:
        hits = _fuzzy_scan(script, global_words, seen_words.copy(), dedupe, n - len(tags))
        _add_tags([(w, off) for w, off, _ in hits], "global_wordlist")
        if hits:
            method_used.append("global_wordlist")

    # Determine effective analysis method
    settings = db.get(AppSettings, 1)
    effective_method = analysis_method or (settings.analysis_method if settings else "algorithmic")
    llm_enabled = profile.llm_enabled and effective_method == "llm"

    # Step 3: LLM (if primary and enabled)
    if len(tags) < n and llm_enabled:
        providers = (
            db.query(LLMProvider)
            .filter(LLMProvider.enabled == True)
            .order_by(LLMProvider.priority)
            .all()
        )
        if profile.llm_provider_id:
            providers = [p for p in providers if p.id == profile.llm_provider_id] + [
                p for p in providers if p.id != profile.llm_provider_id
            ]
        prompt = _build_llm_prompt(script, n, profile_words, global_words)
        try:
            llm_text = asyncio.run(_call_llm_cascade(prompt, providers))
            if llm_text:
                llm_tags = _parse_llm_response(llm_text, n)
                pairs = [
                    (w, max(_find_offset(script_lower, w.lower()), 0))
                    for w in llm_tags
                ]
                _add_tags(pairs, "llm")
                method_used.append("llm")
        except Exception as exc:
            logger.warning("LLM extraction failed: %s", exc)

    # Step 4: spaCy NLP fallback
    if len(tags) < n:
        try:
            nlp_pairs = _spacy_extract(script, n - len(tags), profile_words, global_words, seen_words)
            _add_tags(nlp_pairs, "nlp")
            if nlp_pairs:
                method_used.append("nlp")
        except Exception as exc:
            logger.warning("spaCy extraction failed: %s", exc)

    # Sort by occurrence_index (first appearance in script)
    tags.sort(key=lambda t: t.occurrence_index)
    # Truncate to exactly N
    tags = tags[:n]

    return TagExtractionResult(
        tags=tags,
        count=len(tags),
        needed=n,
        needs_more=len(tags) < n,
        method_used=method_used,
    )
