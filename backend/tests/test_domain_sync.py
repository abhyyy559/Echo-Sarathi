from pathlib import Path

from app.domain_config_service import sync_domain_configs


def test_sync_ignores_schema_json(tmp_path: Path, session_factory) -> None:
    (tmp_path / "schema.json").write_text('{"$schema":"x"}', encoding="utf-8")
    (tmp_path / "absent-student.json").write_text(
        '{"name":"absent-student","display_name":"Absent Student Follow-up"}',
        encoding="utf-8",
    )
    with session_factory() as db:
        names = sync_domain_configs(db, str(tmp_path))
    assert "schema" not in names and "absent-student" in names
