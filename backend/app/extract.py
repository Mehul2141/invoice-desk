"""Reading and field extraction. An LLM (Claude or Gemini) reads the invoice; nothing here decides anything."""
import base64
import json
import logging

from pathlib import Path

import anthropic
import pdfplumber

from .config import (ANTHROPIC_API_KEY, EXTRACTION_EFFORT, GEMINI_API_KEY, GEMINI_FALLBACK_MODELS, GEMINI_MODEL,
                     GEMINI_TIMEOUT_S, MODEL, NARRATIVE_EFFORT, SAMPLES_DIR, provider)

log = logging.getLogger("extract")

_client = None


def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=180, max_retries=2)
    return _client


class ExtractionError(Exception):
    """Permanent failure: retrying the same request will not help."""

    def __init__(self, message, detail=None):
        super().__init__(message)
        self.detail = detail


class TransientExtractionError(ExtractionError):
    """The AI service is busy (rate limit, overload, timeout). Safe to retry later."""

    def __init__(self, message, detail=None, retry_after=None):
        super().__init__(message, detail)
        self.retry_after = retry_after


def _retry_delay_seconds(err):
    """Read Google's RetryInfo.retryDelay (e.g. '37s') from an API error, if present."""
    try:
        for d in (err.details or {}).get("error", {}).get("details", []):
            delay = d.get("retryDelay")
            if delay:
                return float(str(delay).rstrip("s"))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Stage 2: read the document
# ---------------------------------------------------------------------------

def read_document(path):
    with pdfplumber.open(path) as pdf:
        pages = len(pdf.pages)
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        images = sum(len(p.images) for p in pdf.pages)
    chars = len(text.strip())
    scanned = chars < 40
    return {
        "pages": pages,
        "text_chars": chars,
        "image_count": images,
        "is_scanned": scanned,
        "method": "vision (scanned image, no text layer)" if scanned else "native text layer + layout",
        "text_preview": text[:1500],
    }


# ---------------------------------------------------------------------------
# Stage 3: extract fields
# ---------------------------------------------------------------------------

def _nullable(t):
    return {"anyOf": [{"type": t}, {"type": "null"}]}


CONFIDENCE_KEYS = ["vendor_name", "invoice_number", "invoice_date", "po_reference", "line_items", "total",
                   "bank_account"]

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "is_invoice": {"type": "boolean"},
        "vendor_name": _nullable("string"),
        "vendor_address": _nullable("string"),
        "vendor_tax_id": _nullable("string"),
        "vendor_email": _nullable("string"),
        "invoice_number": _nullable("string"),
        "invoice_date": _nullable("string"),
        "due_date": _nullable("string"),
        "currency": _nullable("string"),
        "po_reference": _nullable("string"),
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sku": _nullable("string"),
                    "description": {"type": "string"},
                    "quantity": _nullable("number"),
                    "unit_price": _nullable("number"),
                    "amount": _nullable("number"),
                },
                "required": ["sku", "description", "quantity", "unit_price", "amount"],
                "additionalProperties": False,
            },
        },
        "subtotal": _nullable("number"),
        "tax_amount": _nullable("number"),
        "tax_rate": _nullable("number"),
        "tax_inclusive": {"type": "boolean"},
        "total": _nullable("number"),
        "bank_name": _nullable("string"),
        "bank_account": _nullable("string"),
        "routing_number": _nullable("string"),
        "payment_terms": _nullable("string"),
        "notes": _nullable("string"),
        "field_confidence": {
            "type": "object",
            "properties": {k: {"type": "number"} for k in CONFIDENCE_KEYS},
            "required": CONFIDENCE_KEYS,
            "additionalProperties": False,
        },
        "extraction_warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["is_invoice", "vendor_name", "vendor_address", "vendor_tax_id", "vendor_email", "invoice_number",
                 "invoice_date", "due_date", "currency", "po_reference", "line_items", "subtotal", "tax_amount",
                 "tax_rate", "tax_inclusive", "total", "bank_name", "bank_account", "routing_number",
                 "payment_terms", "notes", "field_confidence", "extraction_warnings"],
    "additionalProperties": False,
}

EXTRACTION_PROMPT = """You are the document-reading step of an accounts-payable pipeline. Read the attached vendor invoice and transcribe its fields into the JSON schema. A separate rules engine makes every approval decision, so your only job is faithful transcription.

Rules:
- Transcribe what the document says. If a field is absent or illegible, return null — never infer or invent values. A missing invoice number must be null, not a guess.
- Dates as YYYY-MM-DD. Amounts as plain numbers without currency symbols or thousands separators. Currency as an ISO code (assume USD only if the document shows $ with no other indication).
- po_reference: any purchase-order reference found anywhere (header, notes, line descriptions), copied exactly as written. Null if there is none.
- line_items: one entry per billed line, with the amounts exactly as printed. Copy SKU/item codes if shown.
- tax_inclusive: true when the line amounts and total already include tax (e.g. "amounts include HST/VAT"); then tax_amount is the included tax and subtotal is the printed subtotal or null if none is printed.
- bank_account / routing_number: digits as printed in the remit-to or payment section, without spaces.
- field_confidence: your confidence 0.0–1.0 that each listed field was read correctly (0 when the field is absent).
- extraction_warnings: short notes on anything ambiguous, illegible, handwritten, or unusual (e.g. "changed bank details notice", "tax shown as included").
- If the document is not an invoice at all, set is_invoice to false."""


def _is_fallback_rejection(err) -> bool:
    return "fallback" in str(err).lower()


def _call_structured(content, schema, effort, max_tokens):
    """One structured-output Messages call with refusal handling.

    Server-side fallbacks are requested so a safety-classifier refusal reroutes instead
    of failing; if this account/SDK rejects the parameter we retry without it.
    """
    params = dict(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    )
    try:
        try:
            resp = client().messages.create(
                **params,
                extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
                extra_body={"fallbacks": "default"},
            )
        except anthropic.BadRequestError as e:
            if not _is_fallback_rejection(e):
                raise
            log.warning("fallbacks parameter rejected, retrying without it: %s", e)
            resp = client().messages.create(**params)
    except anthropic.AuthenticationError as e:
        raise ExtractionError("Anthropic API key was rejected — check backend/.env.") from e
    except anthropic.RateLimitError as e:
        ra = e.response.headers.get("retry-after") if e.response is not None else None
        raise TransientExtractionError("The AI service is rate limiting requests.", str(e),
                                       float(ra) if ra and ra.replace(".", "").isdigit() else None) from e
    except anthropic.APIStatusError as e:
        if e.status_code in (500, 502, 503, 504, 529):
            raise TransientExtractionError("The AI service is temporarily overloaded.", str(e)) from e
        raise ExtractionError(f"Anthropic API error {e.status_code}.", e.message) from e
    except anthropic.APIConnectionError as e:
        raise TransientExtractionError("Could not reach the AI service.", str(e)) from e

    if resp.stop_reason == "refusal":
        raise ExtractionError("The model declined to process this document.")
    if resp.stop_reason == "max_tokens":
        raise ExtractionError("Model output was truncated (max_tokens).")
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        raise ExtractionError("Model returned no structured output.")
    usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
    return json.loads(text), usage


def extract_llm(path):
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode()
    content = [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}},
        {"type": "text", "text": EXTRACTION_PROMPT},
    ]
    result, usage = _call_structured(content, EXTRACTION_SCHEMA, EXTRACTION_EFFORT, 16000)
    return result, {"model": MODEL, **usage}


_gemini = None


def gemini_client():
    global _gemini
    if _gemini is None:
        from google import genai
        from google.genai import types
        # No SDK-level retries: the fallback chain and the job queue's backoff handle that.
        _gemini = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(
            timeout=GEMINI_TIMEOUT_S * 1000, retry_options=types.HttpRetryOptions(attempts=1)))
    return _gemini


def _gemini_models():
    return [GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_MODELS if m != GEMINI_MODEL]


def _gemini_structured(parts, schema, max_tokens, models=None):
    """One Gemini call returning JSON that follows `schema`.

    Free-tier models are often overloaded (503), rate limited (429) or retired for new
    users (404), so each model in GEMINI_MODEL + GEMINI_FALLBACK_MODELS is tried in turn.
    If every model is busy, a TransientExtractionError tells the queue to retry later.
    If a model rejects the schema itself, it is retried in plain JSON mode.
    """
    from google.genai import errors, types

    def call(model, with_schema):
        cfg = dict(response_mime_type="application/json", max_output_tokens=max_tokens)
        if with_schema:
            cfg["response_json_schema"] = schema
        return gemini_client().models.generate_content(
            model=model, contents=parts, config=types.GenerateContentConfig(**cfg))

    resp, used, failures, transient, retry_after = None, None, [], False, None
    for model in models or _gemini_models():
        try:
            try:
                resp = call(model, True)
            except errors.ClientError as e:
                if e.code != 400:
                    raise
                log.warning("%s rejected the response schema, retrying in plain JSON mode: %s", model, e)
                resp = call(model, False)
            used = model
            break
        except errors.ClientError as e:
            if e.code in (401, 403) or "API key" in str(e):
                raise ExtractionError("The Gemini API key was rejected — check GEMINI_API_KEY in backend/.env.",
                                      str(e)) from e
            if e.code not in (404, 429):
                raise ExtractionError(f"Gemini rejected the request (error {e.code}).", str(e.message)) from e
            if e.code == 429:
                transient = True
                retry_after = max(retry_after or 0, _retry_delay_seconds(e) or 0) or retry_after
            failures.append(f"{model}: {'rate limited (429)' if e.code == 429 else 'not available to this key (404)'}")
        except errors.ServerError as e:
            transient = True
            failures.append(f"{model}: overloaded ({e.code})")
        except Exception as e:  # timeouts / network
            transient = True
            failures.append(f"{model}: {type(e).__name__}")
        log.warning("Gemini fallback — %s", failures[-1])
    if resp is None:
        detail = "; ".join(failures)
        if transient:
            raise TransientExtractionError("The AI service is busy (free-tier rate limit or high demand).",
                                           detail, retry_after)
        raise ExtractionError("None of the configured Gemini models is available to this API key.", detail)

    reason = str(resp.candidates[0].finish_reason) if resp.candidates else "no candidates"
    if "MAX_TOKENS" in reason:
        raise TransientExtractionError(f"{used} output was cut off before it finished.", reason)
    text = "".join(p.text for p in (resp.candidates[0].content.parts or []) if getattr(p, "text", None)) \
        if resp.candidates and resp.candidates[0].content else ""
    if not text:
        raise TransientExtractionError(f"{used} returned an empty answer.", f"finish reason: {reason}")
    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        raise TransientExtractionError("Gemini returned malformed JSON.", text[:500]) from e
    um = resp.usage_metadata
    usage = {"model": used, "input_tokens": getattr(um, "prompt_token_count", None),
             "output_tokens": getattr(um, "candidates_token_count", None)}
    if failures:
        usage["fallback_from"] = failures
    return result, usage


def extract_gemini(path):
    from google.genai import types
    parts = [types.Part.from_bytes(data=Path(path).read_bytes(), mime_type="application/pdf"), EXTRACTION_PROMPT]
    result, usage = _gemini_structured(parts, EXTRACTION_SCHEMA, 16000)
    return _fill_defaults(result), usage


def _fill_defaults(result):
    """Guard against fields a model omits when it is not schema-constrained."""
    for key in EXTRACTION_SCHEMA["required"]:
        result.setdefault(key, [] if key in ("line_items", "extraction_warnings") else None)
    result["is_invoice"] = result.get("is_invoice") is not False
    result["tax_inclusive"] = bool(result.get("tax_inclusive"))
    conf = result.get("field_confidence") or {}
    result["field_confidence"] = {k: float(conf.get(k) or 0) for k in CONFIDENCE_KEYS}
    return result


def extract(path, file_hash):
    p = provider()
    if p == "anthropic":
        return extract_llm(path)
    if p == "gemini":
        return extract_gemini(path)
    return extract_mock(file_hash)


def extract_mock(file_hash):
    manifest = json.loads((SAMPLES_DIR / "manifest.json").read_text())
    for s in manifest:
        if s["sha256"] == file_hash:
            return json.loads(json.dumps(s["ground_truth"])), {"model": "mock (stored ground truth)"}
    raise ExtractionError(
        "No AI model is configured, so only the bundled sample invoices can be read.",
        "Add GEMINI_API_KEY or ANTHROPIC_API_KEY to backend/.env to process arbitrary invoices.",
    )


# ---------------------------------------------------------------------------
# Stage 8: plain-English explanation (the decision itself is already made)
# ---------------------------------------------------------------------------

NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "explanation": {"type": "string"},
        "vendor_email": _nullable("string"),
    },
    "required": ["headline", "explanation", "vendor_email"],
    "additionalProperties": False,
}


def narrate(payload, model=None):
    """Best-effort explanation. Uses a single attempt on the model that did the extraction,
    so a busy service costs one quick failure and the caller falls back to a template."""
    prompt = _narrative_prompt(payload)
    if provider() == "gemini":
        result, _ = _gemini_structured([prompt], NARRATIVE_SCHEMA, 4000, models=[model or GEMINI_MODEL])
        return result
    result, _ = _call_structured([{"type": "text", "text": prompt}], NARRATIVE_SCHEMA, NARRATIVE_EFFORT, 4000)
    return result


def _narrative_prompt(payload):
    return (
        "You write the explanation an accounts-payable clerk reads next to an automated invoice decision. "
        "The decision below was made by deterministic rules and is final — explain it, do not change or "
        "second-guess it.\n\n"
        "- headline: one sentence (max ~20 words) stating the decision and the main reason.\n"
        "- explanation: 2–4 short sentences in plain English for a non-technical reader, citing the concrete "
        "numbers, invoice/PO identifiers and checks that drove the outcome. Mention notable non-blocking notes.\n"
        "- vendor_email: only when the vendor must act (a rejection, or missing/incorrect information the vendor "
        "must correct), a short polite email to the vendor's billing contact signed 'Accounts Payable, Harborview "
        "Manufacturing'. Never ask the vendor to confirm changed bank details by replying — bank changes are "
        "verified internally by phone. Otherwise null.\n\n"
        f"Decision record:\n{json.dumps(payload, indent=2, default=str)}"
    )
