from pathlib import Path

from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[1]


def _active_requirements(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in _active_requirements(path):
        if line.startswith("-"):
            continue
        requirement = Requirement(line)
        assert not requirement.extras, f"extras are not lock entries: {line}"
        assert len(requirement.specifier) == 1, f"not an exact pin: {line}"
        specifier = next(iter(requirement.specifier))
        assert specifier.operator == "==", f"not an exact pin: {line}"
        pins[requirement.name.casefold()] = specifier.version
    return pins


def test_python_311_manifest_uses_exact_constraints() -> None:
    requirements = _active_requirements(ROOT / "requirements.txt")
    assert requirements[0] == "-c requirements-constraints-py311.txt"

    for line in requirements[1:]:
        requirement = Requirement(line)
        assert len(requirement.specifier) == 1, f"not an exact pin: {line}"
        assert next(iter(requirement.specifier)).operator == "==", (
            f"not an exact pin: {line}"
        )

    constraints = _pins(ROOT / "requirements-constraints-py311.txt")
    assert constraints["av"] == "14.2.0"
    assert constraints["pyannote.core"] == "5.0.0"
    assert constraints["pyannote.database"] == "5.1.3"
    assert constraints["pyannote.metrics"] == "3.2.1"
    assert constraints["pyannote.pipeline"] == "3.0.1"


def test_torch_profile_is_exact_and_not_duplicated_in_constraints() -> None:
    torch_pins = _pins(ROOT / "requirements-torch-cu121.txt")
    assert torch_pins == {
        "torch": "2.1.1",
        "torchvision": "0.16.1",
        "torchaudio": "2.1.1",
    }

    constraints = _pins(ROOT / "requirements-constraints-py311.txt")
    assert not {"torch", "torchvision", "torchaudio"} & constraints.keys()


def test_manifest_declares_canonical_runtime_without_optional_diarizers() -> None:
    requirements = "\n".join(_active_requirements(ROOT / "requirements.txt"))

    for pin in (
        "ctranslate2==4.6.0",
        "faster-whisper==1.2.1",
        "huggingface-hub==0.36.0",
        "pyannote.audio==3.1.1",
        "llama-cpp-python==0.3.16",
        "aiofiles==23.2.1",
    ):
        assert pin in requirements

    normalized = requirements.casefold().replace("_", "-")
    assert "diart" not in normalized
    assert "resemblyzer" not in normalized
    assert "simple-diarizer" not in normalized
    assert "webrtcvad" not in normalized
    assert "ipython" not in normalized
    assert "typing==" not in normalized
