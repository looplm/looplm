#!/usr/bin/env python3
"""Seed LoopLM with mock LangGraph agent trace data."""

import httpx
import random
import uuid
from datetime import datetime, timedelta, timezone

BASE = "http://localhost:8000"

def main():
    client = httpx.Client(base_url=BASE, timeout=30)

    # 1. Register user
    r = client.post("/api/auth/register", json={"email": "test@looplm.dev", "password": "testpassword123"})
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={"email": "test@looplm.dev", "password": "testpassword123"})
    r.raise_for_status()
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"✅ Auth OK")

    # 2. Create integration
    r = client.post("/api/integrations", json={
        "type": "langsmith",
        "name": "Mock LangGraph Agent",
        "api_key": "mock-api-key-not-real",
        "config": {"project": "mock-langgraph"}
    }, headers=headers)
    if r.status_code == 409:
        r = client.get("/api/integrations", headers=headers)
        integration_id = r.json()["data"][0]["id"]
    else:
        r.raise_for_status()
        integration_id = r.json()["id"]
    print(f"✅ Integration: {integration_id}")

    # 3. Seed traces with spans directly via DB (faster, since no trace creation endpoint exposed)
    # We'll use the API's SQLAlchemy models directly via a helper endpoint... 
    # Actually, let's insert via psycopg2 directly.
    import psycopg2
    import json
    
    conn = psycopg2.connect("postgresql://looplm:looplm@localhost:5432/looplm")
    conn.autocommit = True
    cur = conn.cursor()

    # Get user_id
    cur.execute("SELECT id FROM users LIMIT 1")
    user_id = cur.fetchone()[0]

    now = datetime.now(timezone.utc)
    
    # Graph: START -> router -> [research_agent | writing_agent] -> reviewer -> END
    node_configs = {
        "router": {"type": "chain", "model": "gpt-4o-mini", "base_ms": 200, "var_ms": 300},
        "research_agent": {"type": "agent", "model": "gpt-4o", "base_ms": 800, "var_ms": 2000},
        "writing_agent": {"type": "agent", "model": "gpt-4o", "base_ms": 600, "var_ms": 1500},
        "reviewer": {"type": "llm", "model": "gpt-4o-mini", "base_ms": 300, "var_ms": 800},
    }

    trace_count = 60
    print(f"Seeding {trace_count} traces...")

    for i in range(trace_count):
        trace_id = str(uuid.uuid4())
        ext_id = f"mock-trace-{i:04d}"
        trace_start = now - timedelta(days=random.uniform(0, 7))
        takes_research = random.random() < 0.6
        path = ["router", "research_agent" if takes_research else "writing_agent", "reviewer"]
        
        total_ms = 0
        has_error = False
        spans_data = []
        prev_span_id = None
        
        for node_name in path:
            cfg = node_configs[node_name]
            span_id = str(uuid.uuid4())
            duration = int(cfg["base_ms"] + random.random() * cfg["var_ms"])
            total_ms += duration
            
            is_error = random.random() < 0.07
            if is_error:
                has_error = True
            
            spans_data.append({
                "id": span_id,
                "trace_id": trace_id,
                "parent_span_id": prev_span_id,
                "external_id": f"{ext_id}-{node_name}",
                "name": node_name,
                "type": cfg["type"],
                "model": cfg["model"],
                "tokens_in": random.randint(100, 2000),
                "tokens_out": random.randint(50, 1000),
                "duration_ms": duration,
                "status": "error" if is_error else "ok",
                "error_message": f"LLM timeout in {node_name}" if is_error else None,
                "input": json.dumps({"query": f"Test query {i}"}),
                "output": json.dumps({"result": f"Test output from {node_name}"}),
            })
            prev_span_id = span_id

        trace_end = trace_start + timedelta(milliseconds=total_ms)
        status = "failure" if has_error else "success"
        
        cur.execute("""
            INSERT INTO traces (id, integration_id, external_id, name, start_time, end_time, 
                               duration_ms, status, input, output, metadata, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (
            trace_id, integration_id, ext_id,
            f"LangGraph Agent Run {'(research)' if takes_research else '(writing)'}",
            trace_start, trace_end, total_ms, status,
            json.dumps({"query": f"Test query {i}"}),
            json.dumps({"result": f"Final output {i}"}),
            json.dumps({"path": "research" if takes_research else "writing"}),
            trace_start,
        ))

        for s in spans_data:
            cur.execute("""
                INSERT INTO spans (id, trace_id, parent_span_id, external_id, name, type,
                                  model, tokens_in, tokens_out, duration_ms, status, 
                                  error_message, input, output)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (
                s["id"], s["trace_id"], s["parent_span_id"], s["external_id"],
                s["name"], s["type"], s["model"], s["tokens_in"], s["tokens_out"],
                s["duration_ms"], s["status"], s["error_message"], s["input"], s["output"],
            ))

    print(f"✅ {trace_count} traces with spans inserted")

    # 4. Seed prompts
    prompts = [
        ("router-prompt", "You are a router agent. Given the user query, decide whether to route to research or writing.\n\nQuery: {{query}}\n\nRespond with either 'research' or 'writing'.", ["query"]),
        ("research-agent-prompt", "You are a research agent. Find relevant information for:\n\n{{query}}\n\nContext: {{context}}\n\nProvide detailed research findings.", ["query", "context"]),
        ("writing-agent-prompt", "You are a writing agent. Write content based on:\n\nTopic: {{topic}}\nTone: {{tone}}\nLength: {{length}}\n\nProduce well-structured content.", ["topic", "tone", "length"]),
        ("reviewer-prompt", "Review the following output for quality:\n\n{{content}}\n\nOriginal query: {{query}}\n\nProvide a score (1-10) and suggestions.", ["content", "query"]),
    ]
    
    for name, template, variables in prompts:
        prompt_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO prompts (id, integration_id, external_id, name, template, version, variables, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (
            prompt_id, integration_id, f"mock-{name}", name, template, 1,
            json.dumps(variables), json.dumps({"source": "mock"}),
        ))
    
    print(f"✅ {len(prompts)} prompts inserted")

    # Verify counts
    cur.execute("SELECT COUNT(*) FROM traces")
    print(f"   Traces in DB: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM spans")
    print(f"   Spans in DB: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM prompts")
    print(f"   Prompts in DB: {cur.fetchone()[0]}")

    cur.close()
    conn.close()
    
    # 5. Test endpoints
    print("\n--- Testing Endpoints ---")
    
    r = client.get(f"/api/integrations", headers=headers)
    print(f"GET /api/integrations: {r.status_code} - {len(r.json()['data'])} integrations")
    
    r = client.get(f"/api/route-analysis/{integration_id}", headers=headers)
    print(f"GET /api/route-analysis: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"   Nodes: {len(data.get('nodes', []))}, Edges: {len(data.get('edges', []))}")
    else:
        print(f"   Response: {r.text[:200]}")
    
    r = client.get(f"/api/route-analysis/{integration_id}/bottlenecks", headers=headers)
    print(f"GET /api/route-analysis/bottlenecks: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"   Bottlenecks: {len(data.get('bottlenecks', []))}")
    else:
        print(f"   Response: {r.text[:200]}")
    
    r = client.get(f"/api/prompts", headers=headers)
    print(f"GET /api/prompts: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"   Prompts: {data.get('total', len(data.get('data', [])))}")
    else:
        print(f"   Response: {r.text[:200]}")

    print("\n✅ Seeding complete!")

if __name__ == "__main__":
    main()
