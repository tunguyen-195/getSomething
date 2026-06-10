import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import BinaryIO
from urllib.parse import unquote

from fastapi import HTTPException, UploadFile, status

from src.core.config import settings


CHUNK_SIZE = 1024 * 1024


@dataclass
class StoredAudio:
    original_filename: str
    relative_path: str
    absolute_path: Path
    size: int
    extension: str

    @property
    def download_url(self) -> str:
        return ""


@dataclass
class StagedAudio:
    original_filename: str
    temp_path: Path
    size: int
    extension: str


def audio_root() -> Path:
    root = Path(settings.AUDIO_STORAGE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def sanitize_upload_filename(filename: str | None) -> tuple[str, str]:
    if not filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    decoded = unquote(filename).replace("\x00", "")
    if decoded != PurePath(decoded).name or "/" in decoded or "\\" in decoded:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if decoded in {".", ".."} or ".." in PurePath(decoded).parts:
        raise HTTPException(status_code=400, detail="Invalid filename")

    safe_name = PurePath(decoded).name.strip()
    ext = Path(safe_name).suffix.lower().lstrip(".")
    if not ext or ext not in {e.lower().lstrip(".") for e in settings.ALLOWED_EXTENSIONS}:
        raise HTTPException(status_code=400, detail="Invalid audio extension")
    return safe_name, ext


def _ensure_under_root(path: Path) -> Path:
    root = audio_root()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise HTTPException(status_code=404, detail="Audio file not found")
    return resolved


def resolve_audio_path(file_path: str | None) -> Path:
    if not file_path:
        raise HTTPException(status_code=404, detail="Audio file not found")

    raw = Path(file_path)
    root = audio_root()
    if raw.is_absolute():
        return _ensure_under_root(raw)

    parts = raw.parts
    if len(parts) >= 2 and parts[0] == "storage" and parts[1] == "audio":
        return _ensure_under_root(Path.cwd() / raw)

    return _ensure_under_root(root / raw)


def relative_to_audio_root(path: Path) -> str:
    return str(_ensure_under_root(path).relative_to(audio_root())).replace(os.sep, "/")


def validate_ffprobe_available() -> None:
    try:
        subprocess.run(
            ["ffprobe", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=True,
        )
    except Exception as exc:
        raise RuntimeError("ffprobe is required for audio upload validation") from exc


def validate_audio_content(path: Path) -> None:
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="ffprobe is not available") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=400, detail="Audio validation timed out") from exc

    if proc.returncode != 0 or "audio" not in proc.stdout.lower().splitlines():
        raise HTTPException(status_code=400, detail="Invalid audio content")


def _copy_upload_to_temp(src: BinaryIO, ext: str) -> tuple[Path, int]:
    root = audio_root()
    temp_dir = root / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{uuid.uuid4().hex}.{ext}"
    size = 0
    try:
        with temp_path.open("wb") as out:
            while True:
                chunk = src.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Upload exceeds MAX_UPLOAD_SIZE",
                    )
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="Empty audio file")
        validate_audio_content(temp_path)
        return temp_path, size
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def stage_upload(file: UploadFile) -> StagedAudio:
    original_filename, ext = sanitize_upload_filename(file.filename)
    temp_path, size = _copy_upload_to_temp(file.file, ext)
    return StagedAudio(
        original_filename=original_filename,
        temp_path=temp_path,
        size=size,
        extension=ext,
    )


def finalize_staged_upload(staged: StagedAudio, case_id: int) -> StoredAudio:
    final_dir = audio_root() / "cases" / str(case_id)
    final_dir.mkdir(parents=True, exist_ok=True)
    final_path = final_dir / f"{uuid.uuid4().hex}.{staged.extension}"
    try:
        shutil.move(str(staged.temp_path), str(final_path))
    except Exception:
        staged.temp_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise

    return StoredAudio(
        original_filename=staged.original_filename,
        relative_path=relative_to_audio_root(final_path),
        absolute_path=final_path,
        size=staged.size,
        extension=staged.extension,
    )


def save_upload_to_case(file: UploadFile, case_id: int) -> StoredAudio:
    return finalize_staged_upload(stage_upload(file), case_id)


def cleanup_file(path: Path | None) -> None:
    if not path:
        return
    try:
        _ensure_under_root(path).unlink(missing_ok=True)
    except Exception:
        pass


def media_type_for_filename(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
    }.get(ext, "application/octet-stream")
