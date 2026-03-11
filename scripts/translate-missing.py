#!/usr/bin/env python3
"""
Find and translate missing pt-BR translation keys.

Strategy:
1. Load current pt-BR translation and find keys with empty values.
2. Load previous pt-BR translation (from file or git) to reuse existing translations.
3. For truly new/untranslated keys, call Google Gemini API for AI translation.

Environment variables:
  PREV_TRANSLATION_FILE  - Path to previously translated pt-BR JSON (optional)
  GEMINI_API_KEY         - Google Gemini API key
  AI_MODEL               - Model name (default: gemini-3-flash-preview)

Usage:
    python scripts/translate-missing.py            # Apply translations
    python scripts/translate-missing.py --dry-run  # Preview only
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

PT_BR_PATH = Path("src/lib/i18n/locales/pt-BR/translation.json")
MODELS_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
BATCH_SIZE = 40


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: dict, path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent="\t")
        f.write("\n")


def get_previous_translation() -> dict:
    """Get pt-BR translation from previous version."""
    # Option 1: From file (set by CI workflow)
    prev_file = os.environ.get("PREV_TRANSLATION_FILE")
    if prev_file and Path(prev_file).exists():
        print(f"  Loading previous translation from file: {prev_file}")
        return load_json(Path(prev_file))

    # Option 2: From git (origin/main has the last production translation)
    try:
        result = subprocess.run(
            ["git", "show", f"origin/main:{PT_BR_PATH}"],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
        print("  Loading previous translation from git: origin/main")
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        pass

    print("  No previous translation found, starting fresh")
    return {}


def find_missing_keys(data: dict) -> list[str]:
    """Find keys with empty or whitespace-only values."""
    return [k for k, v in data.items() if not v or not str(v).strip()]


def translate_batch_with_ai(
    keys: list[str],
    context: dict[str, str],
    model: str,
    token: str,
) -> dict[str, str]:
    """Translate a batch of keys using Google Gemini API."""
    if requests is None:
        raise RuntimeError("'requests' package is required: pip install requests")

    keys_dict = {k: "" for k in keys}

    # Select varied context examples (mix short and long translations)
    sorted_ctx = sorted(context.items(), key=lambda x: len(x[1]))
    # Take 20 short, 20 medium, 20 long for diversity
    n = len(sorted_ctx)
    sample_indices = set()
    for start, end in [(0, n // 3), (n // 3, 2 * n // 3), (2 * n // 3, n)]:
        chunk = sorted_ctx[start:end]
        step = max(1, len(chunk) // 20)
        for i in range(0, len(chunk), step):
            sample_indices.add(start + i)
            if len(sample_indices) >= 60:
                break
    context_sample = dict(sorted_ctx[i] for i in sorted(sample_indices) if i < n)

    system_prompt = (
        "Voc├¬ ├⌐ um tradutor especializado em localiza├º├úo de software para pt-BR. "
        "Responda APENAS com um JSON v├ílido contendo as tradu├º├╡es. "
        "Sem explica├º├╡es, sem markdown, sem code blocks."
    )

    user_prompt = f"""Traduza as seguintes chaves de interface de um app web de chat com IA chamado "YuIA".

REGRAS:
1. Traduza de forma natural e fluida para portugu├¬s brasileiro (pt-BR)
2. Use "YuIA" no lugar de "Open WebUI" ou "WebUI"
3. Mantenha placeholders como {{{{variable}}}} intactos
4. Nomes pr├│prios de tecnologia (Docker, Ollama, API, etc.) ficam como est├úo
5. Siglas t├⌐cnicas (HTTPS, URL, API, STT, TTS) ficam como est├úo
6. Se a chave for intraduz├¡vel (nome pr├│prio, sigla isolada), retorne string vazia ""
7. Use vocabul├írio consistente com os exemplos abaixo

Exemplos de tradu├º├╡es existentes para refer├¬ncia de estilo:
{json.dumps(context_sample, ensure_ascii=False, indent=2)}

Chaves para traduzir (retorne APENAS o JSON):
{json.dumps(keys_dict, ensure_ascii=False, indent=2)}"""

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = requests.post(
                MODELS_ENDPOINT, headers=headers, json=payload, timeout=120
            )
            if response.status_code == 429:
                wait = 20 * (2 ** attempt)  # 20s, 40s, 80s, 160s, 320s
                print(f"  Rate limited (429), waiting {wait}s before retry {attempt + 1}/{max_retries}...")
                time.sleep(wait)
                continue
            response.raise_for_status()
            break
        except requests.exceptions.HTTPError:
            if attempt == max_retries - 1:
                raise
    else:
        response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"].strip()

    # Strip markdown code fences if present
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        content = content.rsplit("```", 1)[0].strip()

    return json.loads(content)


def main():
    dry_run = "--dry-run" in sys.argv
    model = os.environ.get("AI_MODEL", "gemini-3-flash-preview")
    token = os.environ.get("GEMINI_API_KEY", "")

    if not PT_BR_PATH.exists():
        print(f"ERROR: {PT_BR_PATH} not found. Run from project root.")
        sys.exit(1)

    # 1. Load current translation
    current = load_json(PT_BR_PATH)
    print(f"Total keys: {len(current)}")

    # 2. Find missing
    missing = find_missing_keys(current)
    print(f"Missing translations: {len(missing)}")

    if not missing:
        print("All keys are translated!")
        return

    # 3. Load previous translation for reuse
    previous = get_previous_translation()
    print(f"Previous version keys: {len(previous)}")

    # 4. Reuse from previous version
    reused = 0
    still_missing = []
    for key in missing:
        prev_value = previous.get(key, "")
        if prev_value and str(prev_value).strip():
            current[key] = prev_value
            reused += 1
        else:
            still_missing.append(key)

    print(f"Reused from previous version: {reused}")
    print(f"Need AI translation: {len(still_missing)}")

    if dry_run:
        print("\n=== DRY RUN - keys that would be sent to AI ===")
        for k in still_missing:
            print(f"  - {k}")
        if not dry_run:
            save_json(current, PT_BR_PATH)
        return

    # 5. Translate with AI
    if still_missing:
        if not token:
            print("\nWARNING: GEMINI_API_KEY not set - skipping AI translation")
            print("Keys still missing:")
            for k in still_missing:
                print(f"  - {k}")
        elif requests is None:
            print("\nWARNING: 'requests' not installed - skipping AI translation")
            print("Install with: pip install requests")
        else:
            context = {k: v for k, v in current.items() if v and str(v).strip()}
            ai_translated = 0
            ai_errors = 0

            total_batches = (len(still_missing) + BATCH_SIZE - 1) // BATCH_SIZE
            for i in range(0, len(still_missing), BATCH_SIZE):
                batch = still_missing[i : i + BATCH_SIZE]
                batch_num = i // BATCH_SIZE + 1

                try:
                    print(
                        f"  Translating batch {batch_num}/{total_batches} ({len(batch)} keys)..."
                    )
                    translated = translate_batch_with_ai(batch, context, model, token)
                    for key, value in translated.items():
                        if key in current and value and str(value).strip():
                            current[key] = value
                            context[key] = value  # Add to context for next batches
                            ai_translated += 1
                except Exception as e:
                    print(f"  ERROR batch {batch_num} failed: {e}")
                    print(f"::warning::AI translation batch {batch_num} failed: {e}")
                    ai_errors += 1

            print(
                f"\nAI translation: {ai_translated} keys translated, {ai_errors} batch errors"
            )

    # 6. Save
    save_json(current, PT_BR_PATH)

    # 7. Report remaining gaps
    final_missing = find_missing_keys(current)
    if final_missing:
        print(f"\nStill missing {len(final_missing)} translations:")
        for k in final_missing[:20]:
            print(f"  - {k}")
        if len(final_missing) > 20:
            print(f"  ... and {len(final_missing) - 20} more")
        # Emit GitHub Actions warning annotation
        keys_preview = ", ".join(final_missing[:5])
        if len(final_missing) > 5:
            keys_preview += f" (+{len(final_missing) - 5} more)"
        print(f"::warning::Tradução pt-BR incompleta: {len(final_missing)} chaves sem tradução — {keys_preview}")
        # Write to GITHUB_OUTPUT if available
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a") as f:
                f.write(f"missing_count={len(final_missing)}\n")
    else:
        print("\nAll keys are now translated!")


if __name__ == "__main__":
    main()
