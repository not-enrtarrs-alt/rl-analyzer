"""Keep essential setup, safety and scheduling guidance present."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_readme_documents_commands_schedule_and_manual_mode():
    text = read("README.md")
    for item in ("doctor --live", "preview", "demo", "history", "19:00", "schtasks", "POST_TO_X=false", "scheduler.log"):
        assert item in text


def test_ballchasing_guide_covers_upload_visibility_and_ids():
    text = read("docs/SETUP_BALLCHASING.md")
    for item in ("does **not** automatically ingest", "Private or unlisted", "/player/<platform>/<id>", "BALLCHASING_TOKEN", "500 list requests/hour"):
        assert item in text


def test_ai_guide_covers_default_and_alternatives():
    text = read("docs/SETUP_AI.md")
    for item in ("ollama pull llama3.1:8b", "ollama serve", "openai", "anthropic", "gemini", "no template fallback"):
        assert item in text


def test_x_guide_documents_permission_cost_and_no_live_testing():
    text = read("docs/SETUP_X.md")
    for item in ("Read and write", "regenerate", "POST_TO_X=false", "$0.015", "$0.200", "https://docs.x.com/x-api/getting-started/pricing", "explicitly authorized"):
        assert item in text


def test_manual_checklist_warns_against_reset_and_live_posting():
    text = read("docs/MANUAL_TEST.md")
    assert "Do not delete or reset" in text
    assert "Do not perform a live X test without explicit authorization" in text
