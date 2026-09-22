import json

import pytest

from app.collectors.disabled import ADR
from app.collectors.errors import DisabledSourceError
from app.core.config import get_settings
from app.jobs import ingest as cli
from app.jobs.celery_app import celery_app
from app.services.ingest import IngestCounts


def test_beat_runs_the_dispatcher_on_the_configured_interval() -> None:
    entry = celery_app.conf.beat_schedule["ingest-all-sources"]
    assert entry["task"] == "app.jobs.tasks.ingest_all_sources"
    assert entry["schedule"] == get_settings().ingest_interval_hours * 3600


def test_tasks_are_registered() -> None:
    celery_app.loader.import_default_modules()
    assert {"app.jobs.tasks.ingest_source", "app.jobs.tasks.ingest_all_sources"} <= set(
        celery_app.tasks
    )


def test_cli_prints_counts_as_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake(name: str, settings: object, *, feeds: object, full: bool) -> IngestCounts:
        assert (name, full) == ("hn", True)
        return IngestCounts(fetched=3, inserted=2, skipped_duplicate=1)

    monkeypatch.setattr(cli, "run_ingest_by_name", fake)
    assert cli.main(["--source", "hn", "--full"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "fetched": 3,
        "inserted": 2,
        "skipped_duplicate": 1,
        "skipped_empty": 0,
    }


def test_cli_reports_a_disabled_source_with_exit_code_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake(*args: object, **kwargs: object) -> IngestCounts:
        raise DisabledSourceError(f"LinkedIn collection is not enabled. See {ADR}.")

    monkeypatch.setattr(cli, "run_ingest_by_name", fake)
    assert cli.main(["--source", "linkedin"]) == 2
    assert ADR in capsys.readouterr().err


def test_cli_rejects_unknown_sources() -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["--source", "tiktok"])
    assert info.value.code == 2
