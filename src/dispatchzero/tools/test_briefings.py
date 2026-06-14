"""20-shot briefing-quality probe — measures valid-JSON rate against the
currently-configured OLLAMA endpoint for the legacy json_object path vs
the new grammar-forced + repair-retry path.

Run inside the app container so config + dependencies resolve normally:

    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T app \\
        python -m dispatchzero.tools.test_briefings [N]

Default N=20. Output is a side-by-side success table plus a sample of
failure messages from each path.

This is a diagnostic — it doesn't write anything to the database, doesn't
exercise the per-user library cache, and doesn't burn rate-limit quota
(it talks to the Ollama client directly, not through the route layer).
"""
import asyncio
import sys
import time

from pydantic import ValidationError

from dispatchzero.config import get_settings
from dispatchzero.integrations.ollama import OllamaClient, OllamaError
from dispatchzero.schemas.missions import MissionContent
from dispatchzero.services.mission_prompts import build_mission_prompt
from dispatchzero.services.missions import (
    _MISSION_JSON_SCHEMA,
    _generate_with_repair,
    _strip_markdown_fences,
)

# Realistic-shape inputs covering all three handler voices and a spread of
# place categories. Names/categories match what the real importer produces.
_TEST_INPUTS: list[dict] = [
    {"name": "Harrington Opera House",     "category": "historic",       "style": "agency", "callsign": "Rook"},
    {"name": "First Presbyterian Church",  "category": "church",         "style": "pulp",   "callsign": "Aria"},
    {"name": "Davenport City Park",        "category": "park",           "style": "guild",  "callsign": "Mira"},
    {"name": "Mountain View Cemetery",     "category": "historic",       "style": "agency", "callsign": "Vault"},
    {"name": "John Day Dam",               "category": "infrastructure", "style": "pulp",   "callsign": "Drift"},
    {"name": "Bonneville Falls",           "category": "park",           "style": "guild",  "callsign": "Cipher"},
    {"name": "Lewis and Clark Bridge",     "category": "infrastructure", "style": "agency", "callsign": "Echo"},
    {"name": "Harrington Post Office",     "category": "civic",          "style": "pulp",   "callsign": "Pike"},
    {"name": "Pacific Crest Trailhead",    "category": "park",           "style": "guild",  "callsign": "Briar"},
    {"name": "Lookout Mountain Fire Tower","category": "infrastructure", "style": "agency", "callsign": "Onyx"},
]


async def _run_legacy_path(client: OllamaClient, messages: list[dict]) -> tuple[bool, str]:
    """Old code path: chat() (json_object), no repair retry. Just like the
    pre-OLMo-2 production behavior was."""
    try:
        raw = await client.chat(messages)
    except OllamaError as e:
        return False, f"transport: {e}"
    cleaned = _strip_markdown_fences(raw)
    try:
        MissionContent.model_validate_json(cleaned)
        return True, ""
    except ValidationError as e:
        # Truncate the Pydantic error so the report stays readable
        return False, f"validation: {str(e).splitlines()[0]}"
    except Exception as e:
        return False, f"parse: {e}"


async def _run_hardened_path(client: OllamaClient, messages: list[dict]) -> tuple[bool, str]:
    """New code path: chat_structured() + repair retry."""
    try:
        await _generate_with_repair(client, messages)
        return True, ""
    except Exception as e:
        return False, str(e).splitlines()[0]


async def main(n: int) -> int:
    settings = get_settings()
    print(f"endpoint:  {settings.ollama_base_url}")
    print(f"model:     {settings.ollama_model}")
    print(f"timeout:   {settings.ollama_timeout_seconds}s")
    print(f"shots:     {n} (interleaved legacy vs hardened against the SAME inputs)")
    print()

    client = OllamaClient(
        api_key=settings.ollama_api_key,
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )

    results: list[dict] = []
    start = time.monotonic()
    try:
        for i in range(n):
            inp = _TEST_INPUTS[i % len(_TEST_INPUTS)]
            messages = build_mission_prompt(
                style=inp["style"],
                place_name=inp["name"],
                place_category=inp["category"],
                place_description=None,
            )
            print(f"[{i+1:2d}/{n}] {inp['style']:7s} {inp['name']!r:42s}", flush=True)

            t0 = time.monotonic()
            legacy_ok, legacy_err = await _run_legacy_path(client, messages)
            t1 = time.monotonic()
            hardened_ok, hardened_err = await _run_hardened_path(client, messages)
            t2 = time.monotonic()

            results.append({
                "input": inp, "legacy_ok": legacy_ok, "legacy_err": legacy_err,
                "hardened_ok": hardened_ok, "hardened_err": hardened_err,
                "legacy_ms": int((t1 - t0) * 1000),
                "hardened_ms": int((t2 - t1) * 1000),
            })

            le = "OK" if legacy_ok else "FAIL"
            he = "OK" if hardened_ok else "FAIL"
            print(f"       legacy:   {le:4s} ({results[-1]['legacy_ms']}ms)"
                  f"   hardened: {he:4s} ({results[-1]['hardened_ms']}ms)")
            if not legacy_ok:
                print(f"         legacy err:   {legacy_err[:140]}")
            if not hardened_ok:
                print(f"         hardened err: {hardened_err[:140]}")
    finally:
        await client.aclose()

    elapsed = time.monotonic() - start
    legacy_passed = sum(r["legacy_ok"] for r in results)
    hardened_passed = sum(r["hardened_ok"] for r in results)

    print()
    print("=" * 60)
    print(f"legacy   (chat + json_object, no retry):    {legacy_passed:2d}/{n}")
    print(f"hardened (chat_structured + repair retry):  {hardened_passed:2d}/{n}")
    print(f"total wall-clock: {elapsed:.1f}s")
    print()
    if hardened_passed > legacy_passed:
        print(f"hardened path recovered {hardened_passed - legacy_passed} "
              f"generation(s) that the legacy path would have surfaced as 503.")

    # Return non-zero if the hardened path didn't meet the 100% acceptance bar.
    return 0 if hardened_passed == n else 1


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    sys.exit(asyncio.run(main(n)))
