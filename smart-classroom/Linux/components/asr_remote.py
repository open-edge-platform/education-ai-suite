"""Transcription stage backed by the audio-analyzer microservice.

Replaces the retired in-process ``ASRComponent``. It uploads the recorded audio
to the containerized audio-analyzer, streams back per-chunk transcription
events, applies the Smart Classroom TEACHER/STUDENT speaker mapping, and
persists the same transcript artifacts the downstream stages (summarizer,
segmentation, report) already consume:

    raw/transcription.txt                        "<SPEAKER>: <text>" per turn
    raw/content_segmentation_transcription.txt   "[start-end] <text>" per turn
    raw/teacher_transcription.txt                "[start-end] <text>" teacher only
    raw/asr_events.jsonl                         per-chunk + final events (UI feed)
"""
import logging
import time

from utils.asr_events import AsrEventWriter
from utils.audio_analyzer_client import AudioAnalyzerClient
from utils.config_loader import config
from utils.session_paths import SessionPaths
from utils.storage_manager import StorageManager

logger = logging.getLogger(__name__)

# ===== Speaker label localization =====
SPEAKER_LABEL_MAP = {
    "en": {"teacher": "TEACHER", "student": "STUDENT", "speaker": "SPEAKER"},
    "zh": {"teacher": "教师", "student": "学生", "speaker": "说话人"},
}


def _get_speaker_labels(lang_code: str) -> dict:
    if not lang_code:
        return SPEAKER_LABEL_MAP["en"]
    lang = lang_code.lower().split("-")[0]
    return SPEAKER_LABEL_MAP.get(lang, SPEAKER_LABEL_MAP["en"])


_LABELS = _get_speaker_labels(getattr(config.app, "language", "en"))
LABEL_TEACHER = _LABELS["teacher"]
LABEL_STUDENT = _LABELS["student"]
LABEL_SPEAKER = _LABELS["speaker"]

_max_chars = getattr(config.models.asr, "max_chars_per_segment", None)
MAX_CHARS_PER_SEGMENT = _max_chars if isinstance(_max_chars, int) and _max_chars > 0 else 0


def _merge_segments(all_segments: list[dict]) -> list[dict]:
    """Merge consecutive same-speaker segments into one turn."""
    merged: list[dict] = []
    for seg in all_segments:
        prev = merged[-1] if merged else None
        if prev is not None and prev["speaker"] == seg["speaker"]:
            if MAX_CHARS_PER_SEGMENT <= 0 or len(prev["text"]) + 1 + len(seg["text"]) <= MAX_CHARS_PER_SEGMENT:
                prev["text"] = f"{prev['text']} {seg['text']}".strip()
                prev["end"] = max(prev["end"], seg["end"])
                continue
        merged.append(dict(seg))
    return merged


def _resolve_display_labels(speaker_text_len: dict[str, int], teacher_raw: str) -> dict:
    """Map raw service speaker ids to TEACHER / STUDENT_n display labels."""
    labels = {teacher_raw: LABEL_TEACHER}
    others = [s for s in speaker_text_len if s != teacher_raw]
    # Stable order: most-talkative student first.
    others.sort(key=lambda s: speaker_text_len.get(s, 0), reverse=True)
    if len(others) == 1:
        labels[others[0]] = LABEL_STUDENT
    else:
        for idx, spk in enumerate(others, start=1):
            labels[spk] = f"{LABEL_STUDENT}_{idx}"
    return labels


def write_transcript_files(
    session_id: str,
    all_segments: list[dict],
    speaker_text_len: dict[str, int],
    primary_speaker: str | None = None,
) -> dict:
    """Apply the TEACHER/STUDENT mapping and write the SC transcript artifacts.

    Shared by the file-upload path (RemoteASRComponent) and the browser live-mic
    path (persist_live_segments). Returns {teacher_speaker, speaker_text_stats}.
    """
    teacher_raw = primary_speaker
    if teacher_raw is None and speaker_text_len:
        teacher_raw = max(speaker_text_len, key=speaker_text_len.get)

    if teacher_raw is not None:
        labels = _resolve_display_labels(speaker_text_len, teacher_raw)
        teacher_lines, full_updated_lines, full_timestamped_lines = [], [], []
        for seg in _merge_segments(all_segments):
            display = labels.get(seg["speaker"], seg["speaker"])
            text = seg["text"].strip()
            s, e = int(seg.get("start", 0)), int(seg.get("end", 0))
            if display == LABEL_TEACHER:
                teacher_lines.append(f"[{s}-{e}] {text}")
            full_updated_lines.append(f"{display}: {text}")
            full_timestamped_lines.append(f"[{s}-{e}] {text}")

        StorageManager.save(str(SessionPaths.transcript_path(session_id)), "\n".join(full_updated_lines) + "\n", append=False)
        StorageManager.save(
            str(SessionPaths.segmentation_transcript_path(session_id)),
            "\n".join(full_timestamped_lines) + "\n",
            append=False,
        )
        StorageManager.save(
            str(SessionPaths.teacher_transcript_path(session_id)),
            "\n".join(teacher_lines) + "\n",
            append=False,
        )

    return {
        "teacher_speaker": LABEL_TEACHER if teacher_raw is not None else None,
        "speaker_text_stats": dict(speaker_text_len),
    }


def persist_live_segments(session_id: str, segments: list[dict], language: str | None = None) -> dict:
    """Persist a browser live-mic transcript into the SC session.

    ``segments`` is a list of {speaker, text, start, end, is_primary?} produced
    by the realtime WebSocket path, so downstream stages (summary, segmentation,
    report) can read the same transcript files the file-upload path writes.
    """
    all_segments: list[dict] = []
    speaker_text_len: dict[str, int] = {}
    primary_speaker: str | None = None
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        raw_spk = seg.get("speaker") or LABEL_TEACHER
        if seg.get("is_primary"):
            primary_speaker = raw_spk
        record = {
            "speaker": raw_spk,
            "text": text,
            "start": float(seg.get("start", 0.0)),
            "end": float(seg.get("end", 0.0)),
        }
        all_segments.append(record)
        speaker_text_len[raw_spk] = speaker_text_len.get(raw_spk, 0) + len(text)

    result = write_transcript_files(session_id, all_segments, speaker_text_len, primary_speaker)
    AsrEventWriter.write(session_id, {"event": "final", **result})
    return result


class RemoteASRComponent:
    """Streams transcription from the audio-analyzer microservice."""

    def __init__(self, session_id: str, temperature: float = 0.0, language: str | None = None):
        self.session_id = session_id
        self.temperature = temperature
        self.language = language or getattr(config.app, "language", "en")
        self.client = AudioAnalyzerClient()
        self.all_segments: list[dict] = []
        self.speaker_text_len: dict[str, int] = {}
        self.primary_speaker: str | None = None

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------
    def process(self, audio_path: str):
        """Yield UI chunk events, then a final speaker-stats event."""
        transcript_path = str(SessionPaths.transcript_path(self.session_id))
        StorageManager.save(transcript_path, "", append=False)

        start = time.perf_counter()
        detected_language = self.language
        try:
            for event in self.client.stream_transcribe(
                audio_path,
                session_id=self.session_id,
                language=self.language,
                temperature=self.temperature,
            ):
                etype = event.get("event")
                if etype == "transcription.chunk":
                    detected_language = event.get("language") or detected_language
                    chunk_result = self._ingest_chunk(event)
                    AsrEventWriter.write(self.session_id, chunk_result)
                    yield chunk_result
                elif etype == "transcription.completed":
                    detected_language = event.get("language") or detected_language

            final_result = self._finalize()
            AsrEventWriter.write(self.session_id, final_result)
            yield final_result
        finally:
            self._write_metrics(round(time.perf_counter() - start, 4), detected_language)
            logger.info("Transcription complete (remote): %s", self.session_id)

    # ------------------------------------------------------------------
    # Per-chunk ingest
    # ------------------------------------------------------------------
    def _ingest_chunk(self, event: dict) -> dict:
        ui_segments: list[dict] = []
        for seg in event.get("segments", []):
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            raw_spk = seg.get("speaker") or LABEL_TEACHER
            if seg.get("is_primary"):
                self.primary_speaker = raw_spk
            record = {
                "speaker": raw_spk,
                "text": text,
                "start": float(seg.get("start", 0.0)),
                "end": float(seg.get("end", 0.0)),
            }
            ui_segments.append(record)
            self.all_segments.append(record)
            self.speaker_text_len[raw_spk] = self.speaker_text_len.get(raw_spk, 0) + len(text)

        return {
            "chunk_index": event.get("chunk_index"),
            "start_time": float(event.get("start_time", 0.0)),
            "end_time": float(event.get("end_time", 0.0)),
            "text": (event.get("text") or "").strip() + "\n",
            "segments": ui_segments,
        }

    # ------------------------------------------------------------------
    # Finalization: TEACHER/STUDENT mapping + transcript files
    # ------------------------------------------------------------------
    def _finalize(self) -> dict:
        result = write_transcript_files(
            self.session_id, self.all_segments, self.speaker_text_len, self.primary_speaker
        )
        return {"event": "final", **result}

    def _write_metrics(self, transcription_time: float, language: str | None) -> None:
        try:
            StorageManager.update_csv(
                path=str(SessionPaths.metrics_path(self.session_id)),
                new_data={
                    "configuration.asr_model": f"audio-analyzer/{config.models.asr.name}",
                    "configuration.diarization": (
                        config.models.diarization.backend if config.models.asr.diarization else "off"
                    ),
                    "configuration.language": language,
                    "performance.transcription_time": transcription_time,
                },
            )
        except Exception as exc:  # noqa: BLE001 - metrics are best-effort
            logger.warning("Failed to write transcription metrics for %s: %s", self.session_id, exc)
