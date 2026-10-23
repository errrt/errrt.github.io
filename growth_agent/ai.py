import json
import os

from .http import request_json


def analyze(snapshot, history):
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")
    if not api_key or not model:
        return {"status": "missing", "error": "OPENAI_API_KEY and OPENAI_MODEL are required", "result": None}

    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "observations": {"type": "array", "items": {"type": "string"}},
            "hypotheses": {"type": "array", "items": {"type": "string"}},
            "opportunities": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "observations", "hypotheses", "opportunities"],
        "additionalProperties": False,
    }
    context = {"today": snapshot, "history": history[-30:]}
    try:
        payload = request_json(
            "https://api.openai.com/v1/responses",
            method="POST",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            body={
                "model": model,
                "instructions": (
                    "個人開発アプリの日次成長snapshotを日本語で分析してください。観測事実と仮説を明確に分離し、"
                    "欠損をゼロとして扱わず、因果関係を断定しないでください。簡潔に答えてください。"
                ),
                "input": json.dumps(context, ensure_ascii=False),
                "max_output_tokens": min(int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "1200")), 2000),
                "text": {"format": {"type": "json_schema", "name": "growth_analysis", "strict": True, "schema": schema}},
            },
        )
        text = next(
            content["text"]
            for item in payload.get("output", []) if item.get("type") == "message"
            for content in item.get("content", []) if content.get("type") == "output_text"
        )
        return {"status": "ok", "error": None, "result": json.loads(text), "usage": payload.get("usage")}
    except Exception as error:
        return {"status": "error", "error": str(error), "result": None}
