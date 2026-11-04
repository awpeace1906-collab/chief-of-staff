"""Speech to text on the server, with local Whisper (see docs/self-contained.md).

Uses faster-whisper (`pip install -e '.[voice]'`), model `base.en` on the CPU with int8. The model loads
once, on first use. COS_WHISPER_MODEL overrides the model name.
"""

import os
import tempfile
import threading

MODEL = "base.en"
_model = None
_lock = threading.Lock()


class VoiceUnavailable(RuntimeError):
    """faster-whisper is not installed."""


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def _load():
    global _model
    with _lock:
        if _model is None:
            try:
                from faster_whisper import WhisperModel
            except ModuleNotFoundError as e:
                if e.name != "faster_whisper":
                    raise VoiceUnavailable(f"faster-whisper is installed but could not load: {e}") from e
                raise VoiceUnavailable("voice transcription needs faster-whisper: pip install -e '.[voice]'") from e
            except ImportError as e:
                raise VoiceUnavailable(f"faster-whisper is installed but could not load: {e}") from e
            _model = WhisperModel(os.environ.get("COS_WHISPER_MODEL") or MODEL, device="cpu", compute_type="int8")
        return _model


def transcribe(audio: bytes, suffix: str = ".m4a") -> str:
    """The spoken text in `audio` (any format ffmpeg reads; the iOS shell sends AAC in .m4a)."""
    model = _load()
    with tempfile.NamedTemporaryFile(suffix=suffix) as f:
        f.write(audio)
        f.flush()
        segments, _ = model.transcribe(f.name, language="en", vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()
