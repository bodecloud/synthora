"""Provider-agnostic structured-output parsing."""

from __future__ import annotations

import json
import re
from typing import Any, Optional


def parse_json_response(text: str) -> Optional[Any]:
    """Extract a JSON object/array from an LLM response.

    Handles bare JSON, fenced ```json blocks, and JSON embedded in prose.
    Works with models lacking native tool calling (e.g. small local models).
    """
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None
