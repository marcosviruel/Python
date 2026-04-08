"""
downloader.py
-------------
Download de arquivos ZIP com retry, resume e watchdog de progresso.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator, Protocol

from rfb.errors import (
    DownloadError,
    DownloadTimeoutError,
    RFBError,
    ResumeNotSupportedError,
)


class DownloaderClientProtocol(Protocol):
    def stream_download(
        self,
        competencia: str,
        nome: str,
        byte_inicial: int = 0
    ) -> object: ...

    def chunks(self, response: object, chunk_size: int) -> Generator: ...


@dataclass
class DownloadMetrics:
    nome: str
    bytes_totais: int = 0
    bytes_retomados: int = 0
    duracao_segundos: float = 0.0
    tentativas: int = 0
    retomado: bool = False

    @property
    def velocidade_media_mbs(self) -> float:
        if self.duracao_segundos <= 0:
            return 0.0
        return self.bytes_totais / self.duracao_segundos / 1_000_000

    @property
    def tamanho_final_mb(self) -> float:
        return (self.bytes_totais + self.bytes_retomados) / 1_000_000

    def __str__(self) -> str:
        retomado_str = (
            f" (retomado de {self.bytes_retomados/1_000_000:.1f}MB)"
            if self.retomado else ""
        )
        return (
            f"{self.nome}{retomado_str} — "
            f"{self.tamanho_final_mb:.1f}MB em {self.duracao_segundos:.0f}s "
            f"({self.velocidade_media_mbs:.1f} MB/s) "
            f"[{self.tentativas} tentativa(s)]"
        )


class Downloader:
    def __init__(
        self,
        client: DownloaderClientProtocol,
        pasta_download: Path,
        chunk_size: int = 8_000_000,
        timeout_total: int = 3600,
        timeout_sem_progresso: int = 300,
        max_tentativas: int = 3,
        intervalo_log: int = 10,
    ):
        self._client = client
        self._pasta = pasta_download
        self._chunk_size = chunk_size
        self._timeout_total = timeout_total
        self._timeout_sem_progresso = timeout_sem_progresso
        self._max_tentativas = max_tentativas
        self._intervalo_log = intervalo_log

    def baixar(self, competencia: str, nome: str) -> DownloadMetrics:
        caminho = self._pasta / nome
        metrics = DownloadMetrics(nome=nome)
        suporta_resume = True

        for tentativa in range(self._max_tentativas):
            metrics.tentativas = tentativa + 1

            try:
                concluido = self._tentar_download(
                    competencia=competencia,
                    nome=nome,
                    caminho=caminho,
                    metrics=metrics,
                    suporta_resume=suporta_resume,
                )

                if concluido:
                    return metrics

            except ResumeNotSupportedError:
                # servidor não suporta Range — reinicia sem penalizar tentativa
                suporta_resume = False
                if caminho.exists():
                    caminho.unlink()
                # não incrementa tentativa — não é falha do arquivo
                continue

            except DownloadTimeoutError as e:
                self._log_retry(nome, tentativa, str(e))
                time.sleep(2 ** tentativa)

            except DownloadError as e:
                # 4xx — falha imediata sem retry
                if e.status_code and 400 <= e.status_code < 500:
                    raise
                self._log_retry(nome, tentativa, str(e))
                time.sleep(2 ** tentativa)

            except Exception as e:
                self._log_retry(nome, tentativa, str(e))
                time.sleep(2 ** tentativa)

        raise DownloadError(
            f"Falha definitiva após {self._max_tentativas} tentativas",
            arquivo=nome
        )

    def ja_baixado(self, nome: str) -> bool:
        caminho = self._pasta / nome
        return caminho.exists() and caminho.stat().st_size > 0

    def _tentar_download(
        self,
        competencia: str,
        nome: str,
        caminho: Path,
        metrics: DownloadMetrics,
        suporta_resume: bool,
    ) -> bool:
        byte_inicial = 0
        if suporta_resume and caminho.exists():
            byte_inicial = caminho.stat().st_size
            if byte_inicial > 0:
                metrics.retomado = True
                metrics.bytes_retomados = byte_inicial

        response = self._client.stream_download(
            competencia=competencia,
            nome=nome,
            byte_inicial=byte_inicial,
        )

        status = getattr(response, "status_code", 200)

        # servidor ignorou Range — não suporta resume
        if byte_inicial > 0 and status == 200:
            raise ResumeNotSupportedError(
                f"Servidor retornou 200 para Range request",
                arquivo=nome,
            )

        # arquivo já completamente baixado
        if status == 416:
            return True

        # FIX: trata status codes diretamente sem depender de exceção
        if 400 <= status < 500:
            raise DownloadError(
                f"HTTP {status} — sem retry",
                arquivo=nome,
                status_code=status,
            )

        if status >= 500:
            raise DownloadError(
                f"HTTP {status} — erro no servidor",
                arquivo=nome,
                status_code=status,
            )

        # modo append para resume, write para download novo
        modo = "ab" if byte_inicial > 0 else "wb"

        inicio = time.monotonic()
        ultimo_chunk = time.monotonic()
        ultimo_log = time.monotonic()
        bytes_trecho = 0
        inicio_trecho = time.monotonic()

        with open(caminho, modo) as f:
            for chunk in self._client.chunks(response, self._chunk_size):
                f.write(chunk)

                agora = time.monotonic()
                # FIX watchdog: ultimo_chunk atualizado apenas aqui
                ultimo_chunk = agora
                metrics.bytes_totais += len(chunk)
                bytes_trecho += len(chunk)

                if agora - ultimo_log >= self._intervalo_log:
                    self._logar_progresso(nome, metrics, bytes_trecho, agora - inicio_trecho)
                    bytes_trecho = 0
                    inicio_trecho = agora
                    ultimo_log = agora

                # FIX watchdog: compara agora com ultimo_chunk (variáveis independentes)
                if agora - ultimo_chunk > self._timeout_sem_progresso:
                    raise DownloadTimeoutError(
                        f"Sem progresso há {agora - ultimo_chunk:.0f}s",
                        arquivo=nome,
                    )

                if agora - inicio > self._timeout_total:
                    raise DownloadTimeoutError(
                        f"Timeout total de {self._timeout_total}s",
                        arquivo=nome,
                    )

        metrics.duracao_segundos += time.monotonic() - inicio
        return True

    def _logar_progresso(
        self,
        nome: str,
        metrics: DownloadMetrics,
        bytes_trecho: int,
        duracao_trecho: float,
    ) -> None:
        velocidade = bytes_trecho / max(duracao_trecho, 0.1) / 1_000_000
        print(f"[ATIVO] {nome} — {metrics.tamanho_final_mb:.1f} MB ({velocidade:.1f} MB/s)")

    def _log_retry(self, nome: str, tentativa: int, motivo: str) -> None:
        print(f"[RETRY {tentativa + 1}/{self._max_tentativas}] {nome} — {motivo}")