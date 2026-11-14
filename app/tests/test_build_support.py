import sys

from account_cleaner import main as main_module
from account_cleaner.core import chrome
from account_cleaner.core.self_test import run_self_test


def test_find_chrome_picks_first_existing(monkeypatch, tmp_path):
    missing, present = tmp_path / "a" / "chrome", tmp_path / "chrome"
    present.write_text("")
    monkeypatch.setattr(chrome, "chrome_candidates", lambda: [missing, present])
    assert chrome.find_chrome() == present
    monkeypatch.setattr(chrome, "chrome_candidates", lambda: [missing])
    assert chrome.find_chrome() is None


def test_chrome_candidates_for_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert any("Google Chrome.app" in str(p) for p in chrome.chrome_candidates())
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("PROGRAMFILES", r"C:\Program Files")
    assert any(p.name == "chrome.exe" for p in chrome.chrome_candidates())


def test_self_test_without_chrome(qapp, monkeypatch):
    monkeypatch.setattr(chrome, "find_chrome", lambda: None)
    checks = {c.name: c for c in run_self_test(require_chrome=False)}
    assert checks["qt"].ok
    assert checks["playwright driver"].ok
    assert checks["chrome"].ok  # 필수가 아니면 없어도 통과
    strict = {c.name: c for c in run_self_test(require_chrome=True)}
    assert not strict["chrome"].ok


def test_self_test_cli_writes_report(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(chrome, "find_chrome", lambda: None)
    report = tmp_path / "report.txt"
    args = main_module.parse_args(["--self-test", "--report", str(report), "-psn_0_123"])
    assert main_module.self_test(args) == 0
    assert "OK   qt" in report.read_text(encoding="utf-8")
