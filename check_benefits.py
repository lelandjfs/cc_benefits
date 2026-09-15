"""
check_benefits.py — semiannual benefits review (runs on GitHub Actions).

Uses the Parallel Task API to research each card's CURRENT official benefit
terms and compares them against RULES in benefits_engine.py. Writes a
markdown report; the workflow opens a GitHub issue from it.

Deliberately does NOT edit benefits_engine.py — this drives real money
tracking, so a human reviews and applies any rule change rather than an
LLM's web research silently rewriting the code.

Env: PARALLEL_API_KEY
Docs: https://docs.parallel.ai/task-api/group-api
"""
import os, json, time, requests
from benefits_engine import RULES

API_KEY = os.environ["PARALLEL_API_KEY"]
BASE = "https://api.parallel.ai"
HEADERS = {"x-api-key": API_KEY, "Content-Type": "application/json"}

TASK_SPEC = (
    "Look up the CURRENT official terms for this specific credit card benefit, "
    "sourced directly from the issuer's own site (americanexpress.com or "
    "chase.com) — not third-party blogs or aggregators. Compare what you find "
    "against the tracked_value/tracked_period given. Report whether the "
    "benefit still exists as a distinct benefit, its current dollar value and "
    "reset period, whether that matches the tracked values, the exact source "
    "URL you used, and any notes (e.g. renamed, merged into another benefit, "
    "merchant list changed)."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "card": {"type": "string"},
        "benefit": {"type": "string"},
        "tracked_value": {"type": "number"},
        "tracked_period": {"type": "string"},
    },
    "required": ["card", "benefit", "tracked_value", "tracked_period"],
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "still_exists": {"type": "boolean"},
        "current_value": {"type": ["number", "null"]},
        "current_period": {"type": ["string", "null"]},
        "matches_tracked_value": {"type": "boolean"},
        "source_url": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["still_exists", "matches_tracked_value", "source_url", "notes"],
}


def create_group():
    r = requests.post(f"{BASE}/v1/tasks/groups", headers=HEADERS, json={}, timeout=30)
    r.raise_for_status()
    return r.json()["taskgroup_id"]


def add_runs(group_id):
    body = {
        "default_task_spec": {
            "input_schema": {"json_schema": INPUT_SCHEMA},
            "output_schema": {"json_schema": OUTPUT_SCHEMA},
            "task_spec": TASK_SPEC,
        },
        "inputs": [
            {
                "input": {
                    "card": rule.card,
                    "benefit": rule.label,
                    "tracked_value": rule.period_value,
                    "tracked_period": rule.period,
                },
                "processor": "pro",
            }
            for rule in RULES
        ],
    }
    r = requests.post(f"{BASE}/v1/tasks/groups/{group_id}/runs", headers=HEADERS, json=body, timeout=30)
    r.raise_for_status()
    return r.json()["run_ids"]


def wait_for_completion(group_id, timeout=900, poll_every=15):
    start = time.time()
    while time.time() - start < timeout:
        r = requests.get(f"{BASE}/v1/tasks/groups/{group_id}", headers=HEADERS, timeout=30)
        r.raise_for_status()
        status = r.json()["status"]
        if not status["is_active"]:
            return status["task_run_status_counts"]
        time.sleep(poll_every)
    raise TimeoutError(f"Parallel task group {group_id} did not finish within {timeout}s")


def fetch_results(group_id):
    results = []
    with requests.get(
        f"{BASE}/v1/tasks/groups/{group_id}/runs",
        headers=HEADERS,
        params={"include_input": "true", "include_output": "true"},
        stream=True,
        timeout=120,
    ) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            event = json.loads(line[len("data:"):].strip())
            run = event.get("run") or {}
            if run.get("status") != "completed":
                continue
            results.append({
                "input": (event.get("input") or {}).get("input", {}),
                "output": (event.get("output") or {}).get("content", {}),
            })
    return results


def build_report(results):
    flagged = []
    sections = []
    for res in results:
        inp, out = res["input"], res["output"]
        label = f"{inp.get('card')} — {inp.get('benefit')}"
        ok = bool(out.get("still_exists")) and bool(out.get("matches_tracked_value"))
        if not ok:
            flagged.append(label)
        tick = "✅" if ok else "⚠️"
        sections.append(
            f"## {tick} {label}\n"
            f"- Tracked: ${inp.get('tracked_value')} / {inp.get('tracked_period')}\n"
            f"- Still exists: {out.get('still_exists')}\n"
            f"- Current: ${out.get('current_value')} / {out.get('current_period')}\n"
            f"- Source: {out.get('source_url')}\n"
            f"- Notes: {out.get('notes') or '—'}\n"
        )

    summary = (
        f"**{len(flagged)} of {len(results)} benefits need a look:** {', '.join(flagged)}\n"
        if flagged else
        f"**All {len(results)} benefits match tracked values.**\n"
    )
    return "# Semiannual benefits review\n\n" + summary + "\n" + "\n".join(sections)


def main():
    group_id = create_group()
    add_runs(group_id)
    wait_for_completion(group_id)
    results = fetch_results(group_id)
    report = build_report(results)
    with open("benefits_review_report.md", "w") as f:
        f.write(report)
    print(f"Wrote benefits_review_report.md ({len(results)} benefits checked)")


if __name__ == "__main__":
    main()
