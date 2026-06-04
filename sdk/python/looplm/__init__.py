"""LoopLM Python SDK — push LLM traces to LoopLM.

    from looplm import LoopLM

    client = LoopLM(api_key="llm_sk_...", base_url="https://your-looplm")

    with client.trace("chat", input={"q": "hi"}, user_id="u1") as t:
        with t.span("llm", name="gpt", model="gpt-4o") as s:
            # ... call your model ...
            s.set_tokens(input=120, output=80)
            s.set_output({"answer": "hello"})
"""

from .client import LoopLM
from .tracing import Span, Trace

__all__ = ["LoopLM", "Trace", "Span"]
__version__ = "0.1.0"
