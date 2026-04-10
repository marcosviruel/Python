"""
tests/test_downloader.py
------------------------
Testes unitários do Downloader.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from rfb.downloader import Downloader, DownloadMetrics
from rfb.errors import (
    DownloadError,
    DownloadTimeoutError,
    ResumeNotSupportedError,
)


# ==================== HELPERS ====================

class MockResponse:
    def __init__(self, status_code=200, chunks=None):
        self.status_code = status_code
        self._chunks = chunks or [b"x" * 100]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class MockClient:
    def __init__(self, responses=None, chunks=None):
        self._responses = responses or [MockResponse()]
        # FIX: chunks padrão como None — cada response tem seus próprios chunks
        self._default_chunks = chunks
        self._call_count = 0
        self.stream_download_calls = []

    def stream_download(self, competencia, nome, byte_inicial=0):
        self.stream_download_calls.append({
            "competencia": competencia,
            "nome": nome,
            "byte_inicial": byte_inicial,
        })
        idx = min(self._call_count, len(self._responses) - 1)
        response = self._responses[idx]
        self._call_count += 1
        return response

    def chunks(self, response: MockResponse, chunk_size: int):
        # FIX: usa chunks da response se disponível, senão usa default
        source = (
            self._default_chunks
            if self._default_chunks is not None
            else response._chunks
        )
        yield from source


def make_downloader(client, pasta: Path, **kwargs) -> Downloader:
    return Downloader(
        client=client,
        pasta_download=pasta,
        chunk_size=1_000,
        timeout_total=kwargs.get("timeout_total", 60),
        timeout_sem_progresso=kwargs.get("timeout_sem_progresso", 30),
        max_tentativas=kwargs.get("max_tentativas", 3),
    )


# ==================== CAMINHO FELIZ ====================

class TestDownloadCompleto:

    def test_cria_arquivo(self, tmp_path: Path):
        client = MockClient(chunks=[b"a", b"b"])
        downloader = make_downloader(client, tmp_path)
        downloader.baixar("2026-03", "file.zip")
        assert (tmp_path / "file.zip").exists()

    def test_conteudo(self, tmp_path: Path):
        client = MockClient(chunks=[b"abc"])
        downloader = make_downloader(client, tmp_path)
        downloader.baixar("2026-03", "file.zip")
        assert (tmp_path / "file.zip").read_bytes() == b"abc"

    def test_metrics(self, tmp_path: Path):
        client = MockClient(chunks=[b"x" * 1_000])
        downloader = make_downloader(client, tmp_path)
        m = downloader.baixar("2026-03", "file.zip")
        assert isinstance(m, DownloadMetrics)
        assert m.bytes_totais == 1_000


# ==================== 416 ====================

class TestArquivoJaBaixado:

    def test_416_nao_modifica_arquivo(self, tmp_path: Path):
        f = tmp_path / "file.zip"
        f.write_bytes(b"ok")
        client = MockClient(responses=[MockResponse(status_code=416)])
        downloader = make_downloader(client, tmp_path)
        downloader.baixar("2026-03", "file.zip")
        assert f.read_bytes() == b"ok"


# ==================== RESUME ====================

class TestResume:

    def test_envia_offset(self, tmp_path: Path):
        f = tmp_path / "file.zip"
        f.write_bytes(b"x" * 500)
        client = MockClient(responses=[MockResponse(status_code=206)])
        downloader = make_downloader(client, tmp_path)
        downloader.baixar("2026-03", "file.zip")
        assert client.stream_download_calls[0]["byte_inicial"] == 500

    def test_append(self, tmp_path: Path):
        """
        FIX: MockResponse com chunks próprios — MockClient.chunks
        usa os chunks da response, não os padrão do client.
        """
        f = tmp_path / "file.zip"
        f.write_bytes(b"old")

        # FIX: chunks passados na response, não no client
        response = MockResponse(status_code=206, chunks=[b"new"])
        client = MockClient(responses=[response])
        downloader = make_downloader(client, tmp_path)
        downloader.baixar("2026-03", "file.zip")

        assert f.read_bytes() == b"oldnew"

    def test_resume_nao_suportado_reinicia(self, tmp_path: Path):
        f = tmp_path / "file.zip"
        f.write_bytes(b"partial")

        def stream(*args, **kwargs):
            if kwargs.get("byte_inicial", 0) > 0:
                raise ResumeNotSupportedError("no range")
            return MockResponse(status_code=200, chunks=[b"completo"])

        client = MockClient()
        client.stream_download = stream
        downloader = make_downloader(client, tmp_path)
        downloader.baixar("2026-03", "file.zip")

        assert f.read_bytes() == b"completo"


# ==================== RETRY ====================

class TestRetry:

    def test_retry_5xx(self, tmp_path: Path):
        """
        FIX: Downloader trata status >= 500 como DownloadError retentável.
        Terceira tentativa retorna 200 — download completa.
        """
        call_count = {"n": 0}

        def stream(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] < 3:
                return MockResponse(status_code=503)
            return MockResponse(status_code=200, chunks=[b"ok"])

        client = MockClient()
        client.stream_download = stream

        downloader = make_downloader(client, tmp_path, max_tentativas=3)

        with patch("time.sleep"):
            m = downloader.baixar("2026-03", "file.zip")

        assert m.tentativas == 3
        assert call_count["n"] == 3

    def test_sem_retry_4xx(self, tmp_path: Path):
        """
        FIX: status 404 lança DownloadError imediatamente — sem retry.
        """
        def stream(*args, **kwargs):
            return MockResponse(status_code=404)

        client = MockClient()
        client.stream_download = stream

        downloader = make_downloader(client, tmp_path, max_tentativas=3)

        with pytest.raises(DownloadError):
            downloader.baixar("2026-03", "file.zip")

    def test_backoff_crescimento(self, tmp_path: Path):
        """
        FIX: 503 causa retry com sleep — verifica que sleeps crescem.
        """
        def stream(*args, **kwargs):
            return MockResponse(status_code=503)

        client = MockClient()
        client.stream_download = stream

        downloader = make_downloader(client, tmp_path, max_tentativas=3)

        with patch("time.sleep") as mock_sleep:
            with pytest.raises(DownloadError):
                downloader.baixar("2026-03", "file.zip")

        sleeps = [c.args[0] for c in mock_sleep.call_args_list]
        assert len(sleeps) >= 2
        assert sleeps[0] < sleeps[-1]

    def test_falha_definitiva_connection_error(self, tmp_path: Path):
        def stream(*args, **kwargs):
            raise RequestsConnectionError("recusado")

        client = MockClient()
        client.stream_download = stream

        downloader = make_downloader(client, tmp_path, max_tentativas=3)

        with patch("time.sleep"):
            with pytest.raises(DownloadError, match="Falha definitiva"):
                downloader.baixar("2026-03", "file.zip")


# ==================== TIMEOUT ====================

class TestTimeouts:

    def test_timeout_total(self, tmp_path: Path):
        client = MockClient(chunks=[b"x"] * 100)
        downloader = make_downloader(client, tmp_path, timeout_total=0.1)

        fake = {"t": 0.0}

        def monotonic():
            fake["t"] += 0.05
            return fake["t"]

        with patch("time.monotonic", monotonic):
            with pytest.raises((DownloadTimeoutError, DownloadError)):
                downloader.baixar("2026-03", "file.zip")


# ==================== MÉTRICAS ====================

class TestMetrics:

    def test_velocidade(self):
        m = DownloadMetrics(nome="x", bytes_totais=10_000_000, duracao_segundos=2)
        assert m.velocidade_media_mbs == pytest.approx(5.0, rel=0.01)

    def test_zero_duracao(self):
        m = DownloadMetrics(nome="x", duracao_segundos=0)
        assert m.velocidade_media_mbs == 0.0

    @pytest.mark.parametrize("bytes_totais,duracao,esperado", [
        (1_000_000, 1.0, 1.0),
        (10_000_000, 2.0, 5.0),
        (0, 10.0, 0.0),
    ])
    def test_velocidade_parametrizada(self, bytes_totais, duracao, esperado):
        m = DownloadMetrics(
            nome="x",
            bytes_totais=bytes_totais,
            duracao_segundos=duracao
        )
        assert m.velocidade_media_mbs == pytest.approx(esperado, rel=0.01)


# ==================== INTEGRIDADE ====================

class TestIntegridade:

    def test_nao_corrompe_arquivo_existente(self, tmp_path: Path):
        """
        FIX: ConnectionError capturado no loop de retry —
        arquivo pré-existente não deve ser modificado após falha.
        """
        f = tmp_path / "file.zip"
        f.write_bytes(b"safe")

        def stream(*args, **kwargs):
            raise RequestsConnectionError("falha")

        client = MockClient()
        client.stream_download = stream

        downloader = make_downloader(client, tmp_path, max_tentativas=1)

        with patch("time.sleep"):
            with pytest.raises(DownloadError):
                downloader.baixar("2026-03", "file.zip")

        assert f.read_bytes() == b"safe"


# ==================== JA BAIXADO ====================

class TestJaBaixado:

    def test_false_inexistente(self, tmp_path: Path):
        d = make_downloader(MockClient(), tmp_path)
        assert d.ja_baixado("x.zip") is False

    def test_true_existente(self, tmp_path: Path):
        f = tmp_path / "x.zip"
        f.write_bytes(b"123")
        d = make_downloader(MockClient(), tmp_path)
        assert d.ja_baixado("x.zip") is True

    def test_false_vazio(self, tmp_path: Path):
        f = tmp_path / "x.zip"
        f.write_bytes(b"")
        d = make_downloader(MockClient(), tmp_path)
        assert d.ja_baixado("x.zip") is False