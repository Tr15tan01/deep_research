"""Shared contracts in packages/shared must match the running code (drift detection)."""

from __future__ import annotations

from app import contracts


def test_shared_contracts_are_current() -> None:
    assert contracts.main(["--check"]) == 0, "run `python -m app.contracts` and commit packages/shared"


def test_every_emitted_stage_is_declared() -> None:
    import re
    from pathlib import Path

    src = "\n".join(p.read_text() for p in (Path(contracts.__file__).parent).rglob("*.py"))
    stages = set(re.findall(r'set_stage\("([a-z_]+)"', src))
    declared = set(contracts.PIPELINE_STAGES) | set(contracts.AUXILIARY_STAGES)
    assert stages <= declared, stages - declared


def test_every_emitted_event_type_is_declared() -> None:
    import re
    from pathlib import Path

    src = "\n".join(p.read_text() for p in (Path(contracts.__file__).parent).rglob("*.py"))
    types = set(re.findall(r'\.emit\("([a-z_]+)"', src)) | set(re.findall(r'emit_event\([^,]+, [^,]+, "([a-z_]+)"', src))
    assert types <= set(contracts.EVENT_TYPES), types - set(contracts.EVENT_TYPES)


def test_env_example_documents_every_setting() -> None:
    import re
    from pathlib import Path

    from app.core.config import Settings

    text = (Path(contracts.ROOT) / ".env.example").read_text()
    keys = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, re.M))
    missing = {k for k in Settings.model_fields if k != "config_warnings"} - keys
    assert not missing, f".env.example is missing: {sorted(missing)}"
    # Docker Compose would treat an inline comment after an empty value as the value itself.
    assert not re.findall(r"^[A-Z_]+=[^\n]*[ \t]#", text, re.M)
    assert not [k for k in re.findall(r"^([A-Z_]*(?:SECRET|PASSWORD|API_KEY|KEYS))=\S", text, re.M) if not k.startswith("ALLOW_")], "secrets must be blank"
