import json
import os

from .http import request_json


ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "observations": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 3,
        },
        "hypotheses": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 3,
        },
        "opportunities": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 3,
        },
    },
    "required": ["summary", "observations", "hypotheses", "opportunities"],
    "additionalProperties": False,
}


def _max_output_tokens():
    try:
        configured = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "4000"))
    except ValueError:
        configured = 4000
    return max(1000, min(configured, 8000))


def _diagnostics(payload):
    details = payload.get("incomplete_details") or {}
    return {
        "response_id": payload.get("id"),
        "model": payload.get("model"),
        "response_status": payload.get("status"),
        "incomplete_reason": details.get("reason"),
        "usage": payload.get("usage"),
    }


def _failure(message, diagnostics=None):
    return {
        "status": "error",
        "error": message,
        "result": None,
        "fallback": "rule_based",
        "diagnostics": diagnostics or {},
    }


def _validate_result(result):
    if not isinstance(result, dict) or set(result) != set(ANALYSIS_SCHEMA["required"]):
        raise ValueError("Structured output did not contain the exact required fields")
    if not isinstance(result["summary"], str):
        raise ValueError("Structured output summary was not a string")
    for key in ("observations", "hypotheses", "opportunities"):
        values = result[key]
        if not isinstance(values, list) or not 1 <= len(values) <= 3:
            raise ValueError(f"Structured output {key} must contain 1 to 3 items")
        if not all(isinstance(value, str) for value in values):
            raise ValueError(f"Structured output {key} contained a non-string item")


def _extract_output_text(payload):
    refusals = [
        content
        for item in payload.get("output", [])
        for content in item.get("content", [])
        if content.get("type") == "refusal"
    ]
    if refusals:
        raise ValueError("OpenAI refused the structured analysis request")

    texts = [
        content.get("text")
        for item in payload.get("output", [])
        if item.get("type") == "message"
        for content in item.get("content", [])
        if content.get("type") == "output_text" and isinstance(content.get("text"), str)
    ]
    if len(texts) != 1:
        raise ValueError(f"Expected exactly one output_text item, received {len(texts)}")
    return texts[0]


def analyze(snapshot, history):
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")
    if not api_key or not model:
        return {
            "status": "missing",
            "error": "OPENAI_API_KEY and OPENAI_MODEL are required",
            "result": None,
            "fallback": "rule_based",
            "diagnostics": {},
        }

    context = {"today": snapshot, "history": history[-30:]}
    body = {
        "model": model,
        "instructions": (
            "個人開発アプリの日次成長snapshotを日本語で分析してください。観測事実と仮説を明確に分離し、"
            "欠損をゼロとして扱わず、因果関係を断定しないでください。各配列は重要度順に最大3件、"
            "各項目は簡潔にしてください。"
        ),
        "input": json.dumps(context, ensure_ascii=False),
        "max_output_tokens": _max_output_tokens(),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "growth_analysis",
                "strict": True,
                "schema": ANALYSIS_SCHEMA,
            }
        },
    }
    reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT", "minimal").strip()
    if reasoning_effort:
        body["reasoning"] = {"effort": reasoning_effort}

    try:
        payload = request_json(
            "https://api.openai.com/v1/responses",
            method="POST",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            body=body,
        )
    except Exception as error:
        return _failure(f"OpenAI request failed: {error}")

    diagnostics = _diagnostics(payload)
    if payload.get("status") != "completed":
        status = payload.get("status") or "unknown"
        reason = diagnostics["incomplete_reason"] or "not_provided"
        return _failure(f"OpenAI response was not completed: status={status}, reason={reason}", diagnostics)

    try:
        text = _extract_output_text(payload)
        try:
            result = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Structured output JSON decode failed at char {error.pos}; output_chars={len(text)}"
            ) from error
        _validate_result(result)
    except Exception as error:
        return _failure(str(error), diagnostics)

    return {
        "status": "ok",
        "error": None,
        "result": result,
        "fallback": None,
        "diagnostics": diagnostics,
    }


def log_line(analysis):
    diagnostics = analysis.get("diagnostics") or {}
    usage = diagnostics.get("usage") or {}
    details = usage.get("output_tokens_details") or {}
    fields = [
        f"status={analysis.get('status', 'unknown')}",
        f"response_id={diagnostics.get('response_id') or 'n/a'}",
        f"model={diagnostics.get('model') or 'n/a'}",
        f"response_status={diagnostics.get('response_status') or 'n/a'}",
        f"incomplete_reason={diagnostics.get('incomplete_reason') or 'n/a'}",
        f"input_tokens={usage.get('input_tokens', 'n/a')}",
        f"output_tokens={usage.get('output_tokens', 'n/a')}",
        f"reasoning_tokens={details.get('reasoning_tokens', 'n/a')}",
        f"fallback={analysis.get('fallback') or 'none'}",
    ]
    if analysis.get("error"):
        fields.append(f"error={analysis['error']}")
    return "AI analysis: " + " ".join(fields)
