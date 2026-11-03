"""Offline tests for portable deployment checks."""
import json

from bot import doctor


def test_ready_when_required_dependencies_exist(tmp_path):
    (tmp_path / ".env").write_text("BOT_TOKEN=placeholder")
    (tmp_path / "config.yaml").write_text("{}")
    report = doctor.inspect_environment(
        python_version=(3, 11), which=lambda name: "/usr/bin/" + name,
        module_available=lambda name: True, project_root=tmp_path)
    assert report["ready"]
    assert all(c["ok"] for c in report["checks"] if c["required"])


def test_missing_dependencies_fail_without_network(tmp_path):
    report = doctor.inspect_environment(
        python_version=(3, 10), which=lambda name: None,
        module_available=lambda name: False, project_root=tmp_path)
    assert not report["ready"]
    assert any(c["name"] == "python" and not c["ok"] for c in report["checks"])
    assert any(c["name"] == "env" and not c["ok"] for c in report["checks"])


def test_json_report_is_machine_readable(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "inspect_environment",
                        lambda: {"ready": True, "checks": []})
    assert doctor.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True


def test_failed_report_has_nonzero_exit(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "inspect_environment",
                        lambda: {"ready": False, "checks": []})
    assert doctor.main([]) == 1
    assert "NOT READY" in capsys.readouterr().out
