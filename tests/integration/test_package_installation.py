"""Artifact and unrelated-CWD startup coverage for recursively packaged QML."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from zipfile import ZipFile


REPOSITORY_ROOT = Path(__file__).parents[2]
EXPECTED_QML = {
    "context_for_ai/ui/qml/Main.qml",
    "context_for_ai/ui/qml/components/ChatPanel.qml",
    "context_for_ai/ui/qml/components/ContextInspectionPage.qml",
    "context_for_ai/ui/qml/components/InspectionCollection.qml",
    "context_for_ai/ui/qml/components/InspectionScalarList.qml",
    "context_for_ai/ui/qml/components/InspectionSection.qml",
}


def build_source_copy(tmp_path: Path) -> Path:
    source = tmp_path / "source-copy"
    source.mkdir()
    shutil.copy2(REPOSITORY_ROOT / "pyproject.toml", source / "pyproject.toml")
    shutil.copytree(REPOSITORY_ROOT / "src", source / "src")
    return source


def run(command: list[str], *, cwd: Path, environment: dict[str, str] | None = None) -> None:
    subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_wheel_and_sdist_include_nested_qml_and_installed_startup_is_cwd_free(
    tmp_path: Path,
    fixture_application_root: Path,
) -> None:
    source = build_source_copy(tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    run(
        [
            sys.executable,
            "-B",
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(artifacts),
        ],
        cwd=source,
    )
    run(
        [
            sys.executable,
            "-B",
            "-c",
            (
                "from setuptools.build_meta import build_sdist; "
                f"build_sdist({str(artifacts)!r})"
            ),
        ],
        cwd=source,
    )

    wheel = next(artifacts.glob("*.whl"))
    sdist = next(artifacts.glob("*.tar.gz"))
    with ZipFile(wheel) as archive:
        wheel_qml = {
            name.removeprefix("context_for_ai/")
            for name in archive.namelist()
            if name.endswith(".qml")
        }
    with tarfile.open(sdist, "r:gz") as archive:
        sdist_qml = {
            name.split("/src/", 1)[1]
            for name in archive.getnames()
            if "/src/" in name and name.endswith(".qml")
        }
    expected_relative = {
        name.removeprefix("context_for_ai/") for name in EXPECTED_QML
    }
    assert wheel_qml == expected_relative
    assert sdist_qml == EXPECTED_QML

    installation = tmp_path / "installed"
    run(
        [
            sys.executable,
            "-B",
            "-m",
            "pip",
            "install",
            str(wheel),
            "--no-deps",
            "--target",
            str(installation),
        ],
        cwd=tmp_path,
    )
    unrelated = tmp_path / "unrelated-working-directory"
    unrelated.mkdir()
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONPATH": str(installation),
            "PYTHONDONTWRITEBYTECODE": "1",
            "QT_QPA_PLATFORM": "offscreen",
        }
    )
    script = """
from pathlib import Path
import sys
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication
import context_for_ai
from context_for_ai.main import bootstrap_application, create_qml_engine, prepare_application_shell
from context_for_ai.ui import ShellFacade

installation = Path(sys.argv[1]).resolve()
configuration_root = Path(sys.argv[2]).resolve()
assert Path(context_for_ai.__file__).resolve().is_relative_to(installation)
startup = bootstrap_application(application_root=configuration_root, environ={})
preparation = prepare_application_shell(startup.scope_factory)
application = QApplication([])
facade = ShellFacade(startup.scope_factory, startup.idempotency_keys)
engine = create_qml_engine(facade)
facade.apply_preparation(preparation)
roots = tuple(engine.rootObjects())
assert len(roots) == 1
assert roots[0].objectName() == "contextForAiRoot"
assert roots[0].findChild(QObject, "chatPanel") is not None
assert roots[0].findChild(QObject, "chatComposer") is not None
assert facade.route == "CHAT"
assert facade.state == "IDLE"
facade.request_shutdown()
engine.deleteLater()
facade.dispose()
facade.deleteLater()
application.processEvents()
print("installed-qml-startup-ok")
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            script,
            str(installation),
            str(fixture_application_root),
        ],
        cwd=unrelated,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.stdout.strip() == "installed-qml-startup-ok"
    assert completed.stderr == ""
