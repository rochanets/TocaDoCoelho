# -*- coding: utf-8 -*-
"""Fase 7.3: Azure Speech F0 para ditados web curtos."""

import wave
from io import BytesIO
from pathlib import Path

import pytest
import requests

import app as toca
import transcription_service as transcription


ROOT = Path(__file__).resolve().parents[1]


def _wav_bytes(
    seconds=1,
    *,
    sample_rate=16_000,
    channels=1,
    sample_width=2,
):
    output = BytesIO()
    frame_count = round(seconds * sample_rate)
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(sample_width)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x00" * frame_count * channels * sample_width)
    return output.getvalue()


def _auth_on(monkeypatch):
    monkeypatch.setenv("TOCA_AUTH_ENABLED", "1")
    monkeypatch.setitem(toca.app.config, "SESSION_COOKIE_SECURE", False)


def _seed_and_login(client):
    conn = toca.get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO organizations (name) VALUES ('Org F7.3')")
    org_id = cur.lastrowid
    cur.execute(
        """INSERT INTO users (org_id, email, full_name, role)
           VALUES (?, 'f73@corp.com', 'Usuária F7.3', 'admin')""",
        (org_id,),
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()
    with client.session_transaction() as session:
        session["user_id"] = user_id
    return user_id


class _AzureResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _AzureClient:
    def __init__(self, response=None, error=None):
        self.response = response or _AzureResponse(
            payload={
                "RecognitionStatus": "Success",
                "DisplayText": "Ditado transcrito",
            }
        )
        self.error = error
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.response


def test_validates_expected_wav_format_and_duration():
    validated = transcription.validate_wav_bytes(
        _wav_bytes(seconds=1.25),
        filename="gravacao.wav",
        declared_mime="audio/wav",
    )

    assert validated.duration_ms == 1250
    assert validated.sample_rate == 16_000
    assert validated.frame_count == 20_000


@pytest.mark.parametrize(
    ("data", "filename", "mime", "expected_code"),
    [
        (b"nao e wav", "gravacao.wav", "audio/wav", "AUDIO_SIGNATURE_MISMATCH"),
        (_wav_bytes(), "gravacao.webm", "audio/webm", "AUDIO_UNSUPPORTED_TYPE"),
        (_wav_bytes(), "gravacao.wav", "audio/webm", "AUDIO_MIME_MISMATCH"),
        (
            _wav_bytes(sample_rate=44_100),
            "gravacao.wav",
            "audio/wav",
            "AUDIO_FORMAT_UNSUPPORTED",
        ),
        (
            _wav_bytes(channels=2),
            "gravacao.wav",
            "audio/wav",
            "AUDIO_FORMAT_UNSUPPORTED",
        ),
    ],
    ids=(
        "fake-wav",
        "webm-extension",
        "wrong-mime",
        "wrong-rate",
        "stereo",
    ),
)
def test_rejects_spoofed_or_unsupported_audio(
    data, filename, mime, expected_code
):
    with pytest.raises(transcription.TranscriptionError) as raised:
        transcription.validate_wav_bytes(
            data,
            filename=filename,
            declared_mime=mime,
        )
    assert raised.value.code == expected_code


def test_rejects_audio_over_55_seconds():
    with pytest.raises(transcription.TranscriptionError) as raised:
        transcription.validate_wav_bytes(
            _wav_bytes(seconds=56),
            filename="longo.wav",
            declared_mime="audio/wav",
        )
    assert raised.value.code == "AUDIO_TOO_LONG"
    assert raised.value.status == 413


def test_rejects_audio_over_byte_limit():
    oversized = _wav_bytes() + b"\x00" * transcription.MAX_AUDIO_BYTES
    with pytest.raises(transcription.TranscriptionError) as raised:
        transcription.validate_wav_bytes(
            oversized,
            filename="grande.wav",
            declared_mime="audio/wav",
        )
    assert raised.value.code == "AUDIO_TOO_LARGE"
    assert raised.value.status == 413


def test_monthly_limit_cannot_exceed_f0_allowance(monkeypatch):
    monkeypatch.setenv("TOCA_TRANSCRIPTION_MONTHLY_MINUTES", "999")
    assert transcription.transcription_monthly_limit_ms() == 300 * 60 * 1000

    monkeypatch.setenv("TOCA_TRANSCRIPTION_MONTHLY_MINUTES", "120")
    assert transcription.transcription_monthly_limit_ms() == 120 * 60 * 1000


def test_rejects_invalid_azure_region(monkeypatch):
    monkeypatch.setenv("AZURE_SPEECH_KEY", "segredo")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "brazilsouth/evil")
    with pytest.raises(transcription.TranscriptionError) as raised:
        transcription.azure_speech_config_from_env()
    assert raised.value.code == "TRANSCRIPTION_INVALID_CONFIG"


def test_azure_request_uses_fixed_endpoint_and_does_not_return_key():
    validated = transcription.validate_wav_bytes(
        _wav_bytes(),
        filename="gravacao.wav",
        declared_mime="audio/wav",
    )
    config = transcription.AzureSpeechConfig(
        key="segredo-azure",
        region="brazilsouth",
    )
    client = _AzureClient()

    text = transcription.transcribe_azure_short_wav(
        validated,
        config,
        http_client=client,
    )

    assert text == "Ditado transcrito"
    args, kwargs = client.calls[0]
    assert args[0] == (
        "https://brazilsouth.stt.speech.microsoft.com/"
        "speech/recognition/conversation/cognitiveservices/v1"
    )
    assert kwargs["params"] == {"language": "pt-BR", "format": "detailed"}
    assert kwargs["headers"]["Ocp-Apim-Subscription-Key"] == "segredo-azure"
    assert "segredo-azure" not in text


def test_azure_timeout_is_controlled_and_keeps_conservative_quota():
    validated = transcription.validate_wav_bytes(
        _wav_bytes(),
        filename="gravacao.wav",
        declared_mime="audio/wav",
    )
    client = _AzureClient(error=requests.Timeout("demorou"))

    with pytest.raises(transcription.TranscriptionError) as raised:
        transcription.transcribe_azure_short_wav(
            validated,
            transcription.AzureSpeechConfig(
                key="segredo",
                region="brazilsouth",
            ),
            http_client=client,
        )
    assert raised.value.code == "TRANSCRIPTION_PROVIDER_TIMEOUT"
    assert raised.value.quota_consumed is True


def test_web_transcription_requires_azure_configuration(client, monkeypatch):
    _auth_on(monkeypatch)
    _seed_and_login(client)
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    monkeypatch.delenv("AZURE_SPEECH_REGION", raising=False)

    response = client.post(
        "/api/transcribe-audio",
        data={
            "audio": (
                BytesIO(_wav_bytes()),
                "gravacao.wav",
                "audio/wav",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 503
    assert response.get_json()["code"] == "TRANSCRIPTION_NOT_CONFIGURED"
    assert toca._transcription_monthly_usage() == 0


def test_web_transcription_records_monthly_usage(client, monkeypatch):
    _auth_on(monkeypatch)
    _seed_and_login(client)
    monkeypatch.setenv("AZURE_SPEECH_KEY", "segredo-teste")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "brazilsouth")
    azure = _AzureClient()
    monkeypatch.setattr(transcription.requests, "post", azure.post)

    response = client.post(
        "/api/transcribe-audio",
        data={
            "audio": (
                BytesIO(_wav_bytes(seconds=2)),
                "gravacao.wav",
                "audio/wav",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["text"] == "Ditado transcrito"
    assert payload["provider"] == "azure-speech-f0"
    assert payload["duration_ms"] == 2000
    assert payload["quota"] == {
        "used_seconds": 2,
        "limit_seconds": 18_000,
    }
    assert toca._transcription_monthly_usage() == 2000


def test_web_quota_stops_request_before_azure(client, monkeypatch):
    _auth_on(monkeypatch)
    _seed_and_login(client)
    monkeypatch.setenv("AZURE_SPEECH_KEY", "segredo-teste")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "brazilsouth")
    limit_ms = transcription.transcription_monthly_limit_ms()
    conn = toca.get_db()
    conn.execute(
        """INSERT INTO transcription_monthly_usage (period_key, used_ms)
           VALUES (?, ?)""",
        (toca._transcription_period_key(), limit_ms - 500),
    )
    conn.commit()
    conn.close()
    azure = _AzureClient()
    monkeypatch.setattr(transcription.requests, "post", azure.post)

    response = client.post(
        "/api/transcribe-audio",
        data={
            "audio": (
                BytesIO(_wav_bytes(seconds=1)),
                "gravacao.wav",
                "audio/wav",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 429
    assert response.get_json()["code"] == "TRANSCRIPTION_MONTHLY_QUOTA_REACHED"
    assert azure.calls == []
    assert toca._transcription_monthly_usage() == limit_ms - 500


def test_azure_auth_failure_releases_reserved_quota(client, monkeypatch):
    _auth_on(monkeypatch)
    _seed_and_login(client)
    monkeypatch.setenv("AZURE_SPEECH_KEY", "credencial-invalida")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "brazilsouth")
    azure = _AzureClient(response=_AzureResponse(status_code=401))
    monkeypatch.setattr(transcription.requests, "post", azure.post)

    response = client.post(
        "/api/transcribe-audio",
        data={
            "audio": (
                BytesIO(_wav_bytes()),
                "gravacao.wav",
                "audio/wav",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 503
    assert response.get_json()["code"] == "TRANSCRIPTION_PROVIDER_AUTH_FAILED"
    assert toca._transcription_monthly_usage() == 0


def test_web_rejects_legacy_webm_before_provider(client, monkeypatch):
    _auth_on(monkeypatch)
    _seed_and_login(client)
    monkeypatch.setenv("AZURE_SPEECH_KEY", "segredo-teste")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "brazilsouth")

    response = client.post(
        "/api/transcribe-audio",
        data={
            "audio": (
                BytesIO(b"webm legado"),
                "gravacao.webm",
                "audio/webm",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 415
    assert response.get_json()["code"] == "AUDIO_UNSUPPORTED_TYPE"


def test_desktop_keeps_local_faster_whisper_flow(client, monkeypatch):
    monkeypatch.delenv("TOCA_AUTH_ENABLED", raising=False)
    monkeypatch.setattr(toca, "WHISPER_AVAILABLE", True)
    monkeypatch.setattr(toca, "configure_ffmpeg_for_whisper", lambda: None)

    class _Segment:
        text = " Texto desktop"

    class _Model:
        def transcribe(self, _path, language):
            assert language == "pt"
            return [_Segment()], {}

    monkeypatch.setattr(toca, "get_whisper_model", lambda: _Model())

    response = client.post(
        "/api/transcribe-audio",
        data={
            "audio": (
                BytesIO(b"webm aceito pelo fluxo desktop"),
                "gravacao.webm",
                "audio/webm",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json()["text"] == "Texto desktop"


def test_frontend_encodes_wav_and_stops_at_55_seconds():
    script = (
        ROOT / "public" / "js" / "itoca-autotoca.js"
    ).read_text(encoding="utf-8")
    page = (ROOT / "public" / "index.html").read_text(encoding="utf-8")

    assert "const VOICE_MAX_RECORDING_MS = 55 * 1000;" in script
    assert "function encodePcm16Wav" in script
    assert "convertRecordedAudioToWav" in script
    assert "formData.append('audio', wavBlob, 'gravacao.wav')" in script
    assert "}, VOICE_MAX_RECORDING_MS);" in script
    assert page.count('aria-label="Gravar áudio — máximo de 55 segundos"') == 2
