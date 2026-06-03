"""End-to-end smoke test for the LoopLM tracing SDK.

Usage:
    LOOPLM_API_KEY=llm_sk_... LOOPLM_BASE_URL=http://localhost:8000 \
        python sdk/python/examples/quickstart.py

Emits one trace with a chain → (llm, tool) span tree, then flushes. Check the
LoopLM Traces view for a trace named "demo-chat".
"""

import os
import time

from looplm import LoopLM


def main() -> None:
    api_key = os.environ["LOOPLM_API_KEY"]
    base_url = os.environ.get("LOOPLM_BASE_URL", "http://localhost:8000")

    client = LoopLM(api_key=api_key, base_url=base_url)

    with client.trace("demo-chat", input={"question": "What is LoopLM?"}, user_id="demo-user") as t:
        with t.span("chain", name="agent") as chain:
            with t.span("llm", name="answer", model="gpt-4o") as s:
                time.sleep(0.05)  # pretend to call a model
                s.set_tokens(input=120, output=80)
                s.set_output({"answer": "An LLM debugging and evaluation platform."})

            with t.span("tool", name="web_search") as s:
                time.sleep(0.02)
                s.set_output({"hits": 3})

        t.set_output({"answer": "An LLM debugging and evaluation platform."})

    client.flush()
    print("Sent trace 'demo-chat'. Check the LoopLM Traces view.")


if __name__ == "__main__":
    main()
