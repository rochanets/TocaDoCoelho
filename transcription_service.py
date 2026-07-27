"""Validação e integração leve de transcrição para o runtime web.

O servidor web usa somente a API REST de áudio curto do Azure Speech F0.
`faster-whisper` continua sendo carregado sob demanda pelo runtime desktop.
"""

from __future__ import annotations

import os
import re
import wave
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import requests


AZURE_SPEECH_LANGUAGE = "pt-BR"
MAX_AUDIO_SECONDS = 55
MAX_AUDIO_BYTES = 2 * 1024 * 1024
MONTHLY_FREE_MINUTES = 300

_ALLOWED_WAV_MIMES = {
    "",
    "application/octet-stream",
    "audio/wav",
    "audio/wave",
    "audio/x-wav",
}
_AZURE_REGION_RE = re.compile(r"^[a-z0-9-]+$")


class TranscriptionError(ValueError):
    """Erro controlado de configuração, validação ou provedor."""

    def __init__(
        self,
        message,
        *,
        code,
        status=422,
        hint=None,
        quota_consumed=False,
    ):
        super().__init__(message)
        self.code = code
        self.status = int(status)
        self.hint = hint
        self.quota_consumed = bool(quota_consumed)

    def to_payload(self):
        payload = {"error": str(self), "code": self.code}
        if self.hint:
            payload["hint"] = self.hint
        return payload


@dataclass(frozen=True)
class ValidatedWav:
    data: bytes
    duration_ms: int
    frame_count: int
    sample_rate: int


@dataclass(frozen=True)
class AzureSpeechConfig:
    key: str
    region: str
    language: str = AZURE_SPEECH_LANGUAGE

    @property
    def endpoint(self):
        return (
            f"https://{self.region}.stt.speech.microsoft.com/"
            "speech/recognition/conversation/cognitiveservices/v1"
        )


def _normalized_mime(value):
    return (value or "").split(";", 1)[0].strip().lower()


def azure_speech_config_from_env():
    key = (os.environ.get("AZURE_SPEECH_KEY") or "").strip()
    region = (os.environ.get("AZURE_SPEECH_REGION") or "").strip().lower()
    if not key or not region:
        raise TranscriptionError(
            "A transcrição online ainda não foi configurada.",
            code="TRANSCRIPTION_NOT_CONFIGURED",
            status=503,
            hint=(
                "Configure AZURE_SPEECH_KEY e AZURE_SPEECH_REGION com um "
                "recurso Azure Speech F0."
            ),
        )
    if not _AZURE_REGION_RE.fullmatch(region):
        raise TranscriptionError(
            "A região configurada para o Azure Speech é inválida.",
            code="TRANSCRIPTION_INVALID_CONFIG",
            status=503,
        )
    return AzureSpeechConfig(key=key, region=region)


def transcription_monthly_limit_ms():
    """Permite reduzir o teto, mas nunca ultrapassar as cinco horas do F0."""
    raw = (os.environ.get("TOCA_TRANSCRIPTION_MONTHLY_MINUTES") or "").strip()
    try:
        configured = int(raw) if raw else MONTHLY_FREE_MINUTES
    except ValueError:
        configured = MONTHLY_FREE_MINUTES
    minutes = min(MONTHLY_FREE_MINUTES, max(1, configured))
    return minutes * 60 * 1000


def validate_wav_bytes(data, *, filename, declared_mime=""):
    data = bytes(data or b"")
    if not data:
        raise TranscriptionError(
            "O áudio enviado está vazio.",
            code="AUDIO_EMPTY",
            status=400,
        )
    if len(data) > MAX_AUDIO_BYTES:
        raise TranscriptionError(
            "O áudio excede o limite permitido.",
            code="AUDIO_TOO_LARGE",
            status=413,
            hint=f"Limite: {MAX_AUDIO_BYTES} bytes.",
        )

    if Path(filename or "").suffix.lower() != ".wav":
        raise TranscriptionError(
            "A transcrição web aceita somente áudio WAV.",
            code="AUDIO_UNSUPPORTED_TYPE",
            status=415,
        )
    if _normalized_mime(declared_mime) not in _ALLOWED_WAV_MIMES:
        raise TranscriptionError(
            "O tipo MIME declarado não corresponde a um áudio WAV.",
            code="AUDIO_MIME_MISMATCH",
            status=415,
        )
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise TranscriptionError(
            "O conteúdo não corresponde a um WAV válido.",
            code="AUDIO_SIGNATURE_MISMATCH",
            status=415,
        )

    try:
        with wave.open(BytesIO(data), "rb") as audio:
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
            sample_rate = audio.getframerate()
            frame_count = audio.getnframes()
            compression = audio.getcomptype()
            frames = audio.readframes(frame_count)
    except (EOFError, wave.Error) as exc:
        raise TranscriptionError(
            "O arquivo WAV está corrompido ou malformado.",
            code="AUDIO_MALFORMED",
        ) from exc

    if (
        channels != 1
        or sample_width != 2
        or sample_rate != 16_000
        or compression != "NONE"
    ):
        raise TranscriptionError(
            "O WAV deve usar PCM mono, 16 bits e 16 kHz.",
            code="AUDIO_FORMAT_UNSUPPORTED",
            status=415,
        )
    expected_bytes = frame_count * channels * sample_width
    if frame_count <= 0 or len(frames) != expected_bytes:
        raise TranscriptionError(
            "O arquivo WAV não contém amostras de áudio válidas.",
            code="AUDIO_MALFORMED",
        )

    duration_ms = max(1, round(frame_count * 1000 / sample_rate))
    if duration_ms > MAX_AUDIO_SECONDS * 1000:
        raise TranscriptionError(
            "A gravação excede o limite de 55 segundos.",
            code="AUDIO_TOO_LONG",
            status=413,
            hint=f"Máximo: {MAX_AUDIO_SECONDS} segundos por gravação.",
        )
    return ValidatedWav(
        data=data,
        duration_ms=duration_ms,
        frame_count=frame_count,
        sample_rate=sample_rate,
    )


def read_wav_upload(file_storage):
    if not file_storage or not getattr(file_storage, "filename", ""):
        raise TranscriptionError(
            "Arquivo de áudio não enviado.",
            code="AUDIO_MISSING",
            status=400,
        )
    data = file_storage.read(MAX_AUDIO_BYTES + 1)
    return validate_wav_bytes(
        data,
        filename=file_storage.filename,
        declared_mime=getattr(file_storage, "mimetype", ""),
    )


def transcribe_azure_short_wav(validated_wav, config, *, http_client=requests):
    """Envia WAV já validado à API REST de áudio curto do Azure Speech."""
    try:
        response = http_client.post(
            config.endpoint,
            params={"language": config.language, "format": "detailed"},
            headers={
                "Accept": "application/json",
                "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
                "Ocp-Apim-Subscription-Key": config.key,
            },
            data=validated_wav.data,
            timeout=(5, 75),
        )
    except requests.Timeout as exc:
        raise TranscriptionError(
            "O Azure Speech demorou além do limite para responder.",
            code="TRANSCRIPTION_PROVIDER_TIMEOUT",
            status=504,
            quota_consumed=True,
        ) from exc
    except requests.RequestException as exc:
        raise TranscriptionError(
            "Não foi possível conectar ao Azure Speech.",
            code="TRANSCRIPTION_PROVIDER_UNAVAILABLE",
            status=503,
            quota_consumed=True,
        ) from exc

    if response.status_code in (401, 403):
        raise TranscriptionError(
            "A credencial do Azure Speech foi recusada.",
            code="TRANSCRIPTION_PROVIDER_AUTH_FAILED",
            status=503,
        )
    if response.status_code == 429:
        raise TranscriptionError(
            "A transcrição está ocupada ou a franquia mensal foi atingida.",
            code="TRANSCRIPTION_BUSY_OR_QUOTA",
            status=429,
            hint="Aguarde uma transcrição em andamento ou confirme a franquia F0.",
        )
    if response.status_code >= 500:
        raise TranscriptionError(
            "O Azure Speech está temporariamente indisponível.",
            code="TRANSCRIPTION_PROVIDER_UNAVAILABLE",
            status=503,
        )
    if response.status_code >= 400:
        raise TranscriptionError(
            "O Azure Speech recusou o formato do áudio.",
            code="TRANSCRIPTION_PROVIDER_REJECTED",
            status=422,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise TranscriptionError(
            "O Azure Speech retornou uma resposta inválida.",
            code="TRANSCRIPTION_PROVIDER_INVALID_RESPONSE",
            status=502,
            quota_consumed=True,
        ) from exc

    status = str(payload.get("RecognitionStatus") or "")
    text = str(payload.get("DisplayText") or "").strip()
    if not text:
        alternatives = payload.get("NBest") or []
        if alternatives and isinstance(alternatives[0], dict):
            text = str(alternatives[0].get("Display") or "").strip()
    if status != "Success" or not text:
        raise TranscriptionError(
            "Não foi possível identificar fala na gravação.",
            code="TRANSCRIPTION_NO_SPEECH",
            hint="Fale próximo ao microfone e tente novamente.",
            quota_consumed=True,
        )
    return text
