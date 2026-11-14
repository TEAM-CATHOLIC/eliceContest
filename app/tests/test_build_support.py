import sys

from account_cleaner import main as main_module
from account_cleaner.core import chrome
from account_cleaner.core.self_test import run_self_test


def test_Chrome_후보_위치_중_처음으로_존재하는_파일을_고른다(monkeypatch, tmp_path):
    # given: 없는 위치와 있는 위치
    missing, present = tmp_path / "a" / "chrome", tmp_path / "chrome"
    present.write_text("")
    monkeypatch.setattr(chrome, "chrome_candidates", lambda: [missing, present])

    # when
    found = chrome.find_chrome()

    # then
    assert found == present


def test_Chrome_후보_위치가_모두_없으면_None을_돌려준다(monkeypatch, tmp_path):
    # given
    monkeypatch.setattr(chrome, "chrome_candidates", lambda: [tmp_path / "없음"])

    # when / then
    assert chrome.find_chrome() is None


def test_OS별로_Chrome_기본_설치_위치를_후보로_삼는다(monkeypatch):
    # given / when: macOS
    monkeypatch.setattr(sys, "platform", "darwin")
    mac = chrome.chrome_candidates()

    # given / when: Windows
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("PROGRAMFILES", r"C:\Program Files")
    windows = chrome.chrome_candidates()

    # then
    assert any("Google Chrome.app" in str(p) for p in mac)
    assert any(p.name == "chrome.exe" for p in windows)


def test_Chrome이_없어도_필수가_아니면_self_test는_통과한다(qapp, monkeypatch):
    # given
    monkeypatch.setattr(chrome, "find_chrome", lambda: None)

    # when
    checks = {c.name: c for c in run_self_test(require_chrome=False)}

    # then
    assert checks["qt"].ok
    assert checks["playwright driver"].ok
    assert checks["chrome"].ok


def test_Chrome이_필수인데_없으면_self_test는_실패한다(qapp, monkeypatch):
    # given
    monkeypatch.setattr(chrome, "find_chrome", lambda: None)

    # when
    checks = {c.name: c for c in run_self_test(require_chrome=True)}

    # then
    assert not checks["chrome"].ok


def test_self_test_옵션은_모르는_인자를_무시하고_결과를_파일로_쓴다(qapp, monkeypatch, tmp_path):
    # given: macOS가 붙이는 -psn_ 인자가 섞인 명령줄
    monkeypatch.setattr(chrome, "find_chrome", lambda: None)
    report = tmp_path / "report.txt"
    args = main_module.parse_args(["--self-test", "--report", str(report), "-psn_0_123"])

    # when
    code = main_module.self_test(args)

    # then
    assert code == 0
    assert "OK   qt" in report.read_text(encoding="utf-8")
