"""
pipeline.py
-----------
Orquestração do pipeline de download e extração de dados da RFB.

Responsabilidade única:
    Coordenar a execução das etapas do pipeline — listagem, download,
    validação, extração — sem implementar nenhuma delas.
    É o maestro, não o músico.

Separação download vs extração:
    Download e extração rodam em pools separados com uma Queue
    entre eles — padrão produtor/consumidor.

    Por quê?
    Download = I/O de rede   (gargalo: banda)
    Extração = I/O de disco  (gargalo: velocidade do disco)

    Com pools separados, enquanto um arquivo extrai (usando disco),
    os outros workers continuam baixando (usando rede) — os dois
    recursos são usados simultaneamente em vez de sequencialmente.

    Diagrama:
        Download pool (3 workers)     Extração pool (1 worker)
        ─────────────────────────     ────────────────────────
        [baixa A] ──────────────────► [extrai A]
        [baixa B] ──► queue           [extrai B]
        [baixa C] ──► queue           [extrai C]
                      queue ─────────► [extrai D]

    O pool de extração usa 1 worker intencionalmente:
    extração é sequencial no disco — múltiplos workers disputariam
    o mesmo I/O sem ganho de throughput.

Idempotência:
    O pipeline verifica arquivos já processados antes de qualquer
    operação. Re-executar é sempre seguro — arquivos concluídos
    são pulados sem re-download ou re-extração.

Observabilidade:
    Cada etapa loga seu início, conclusão e duração.
    Ao final, um sumário mostra sucessos, falhas e tempo total —
    sem precisar varrer o log para entender o resultado.
"""

from __future__ import annotations

import logging
import queue
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import Config
from .client import RFBClient, ArquivoInfo
from .downloader import Downloader, DownloadMetrics
from .extractor import Extractor
from .validator import Validator
from .errors import (
    CompetenciaNotFoundError,
    DownloadError,
    ExtractionError,
    InsufficientDiskSpaceError,
    ListingError,
    RFBError,
    RenameError,
    ValidationError,
)

logger = logging.getLogger("rfb.pipeline")


# ==================== RESULTADO POR ARQUIVO ====================

@dataclass
class ResultadoArquivo:
    """
    Resultado do processamento de um arquivo individual.

    Agrega o status de todas as etapas (download, validação, extração)
    para um arquivo específico — usado no sumário final do pipeline.

    Attributes:
        nome: nome do arquivo ZIP
        sucesso: True se todas as etapas completaram sem erro
        erro: mensagem de erro se sucesso=False
        etapa_falha: etapa onde ocorreu a falha (download/validação/extração)
        metrics: métricas de download (None se download não completou)
        duracao_total: tempo total de processamento em segundos
    """
    nome: str
    sucesso: bool = False
    erro: str = ""
    etapa_falha: str = ""
    metrics: Optional[DownloadMetrics] = None
    duracao_total: float = 0.0

    def __str__(self) -> str:
        if self.sucesso:
            velocidade = (
                f" | {self.metrics.velocidade_media_mbs:.1f} MB/s"
                if self.metrics else ""
            )
            return f"✓ {self.nome} ({self.duracao_total:.0f}s{velocidade})"
        return f"✗ {self.nome} | {self.etapa_falha}: {self.erro}"


# ==================== SUMÁRIO DO PIPELINE ====================

@dataclass
class SumarioPipeline:
    """
    Sumário agregado do resultado do pipeline completo.

    Exibido ao final da execução para visão rápida do resultado
    sem precisar varrer centenas de linhas de log.

    Attributes:
        competencia: competência processada
        total: total de arquivos tentados
        sucessos: arquivos processados com sucesso
        falhas: arquivos que falharam em alguma etapa
        pulados: arquivos pulados por já estarem processados
        duracao_total: tempo total do pipeline em segundos
        resultados: resultado individual de cada arquivo
    """
    competencia: str
    total: int = 0
    sucessos: int = 0
    falhas: int = 0
    pulados: int = 0
    duracao_total: float = 0.0
    resultados: list[ResultadoArquivo] = field(default_factory=list)

    def logar(self) -> None:
        """Loga sumário estruturado ao final do pipeline."""
        logger.info("=" * 60)
        logger.info(f"SUMÁRIO — competência {self.competencia}")
        logger.info("=" * 60)
        logger.info(
            f"Total: {self.total} | "
            f"Sucesso: {self.sucessos} | "
            f"Falhas: {self.falhas} | "
            f"Pulados: {self.pulados}"
        )
        logger.info(f"Tempo total: {self.duracao_total:.0f}s")
        logger.info("-" * 60)

        # lista sucessos primeiro, depois falhas
        for r in sorted(self.resultados, key=lambda x: (not x.sucesso, x.nome)):
            logger.info(str(r))

        logger.info("=" * 60)

        if self.falhas > 0:
            logger.warning(
                f"{self.falhas} arquivo(s) falharam — "
                f"re-execute o pipeline para re-tentar"
            )


# ==================== PIPELINE ====================

class Pipeline:
    """
    Orquestra o pipeline completo de dados da RFB.

    Coordena as etapas sem implementar nenhuma delas:
        1. Verificação de espaço em disco
        2. Listagem de arquivos disponíveis
        3. Download paralelo (pool de workers)
        4. Validação + Extração paralela ao download (fila)
        5. Limpeza de arquivos temporários
        6. Sumário do resultado

    Todos os componentes são injetados no construtor —
    permite substituição por mocks em testes unitários.

    Exemplo de uso:
        cfg = Config.from_env()

        with RFBClient(token=cfg.token) as client:
            pipeline = Pipeline.from_config(cfg, client)
            sumario = pipeline.executar()

        sumario.logar()
    """

    def __init__(
        self,
        cfg: Config,
        client: RFBClient,
        downloader: Downloader,
        validator: Validator,
        extractor: Extractor,
    ):
        self._cfg = cfg
        self._client = client
        self._downloader = downloader
        self._validator = validator
        self._extractor = extractor

    @classmethod
    def from_config(cls, cfg: Config, client: RFBClient) -> "Pipeline":
        """
        Factory method — cria Pipeline com componentes padrão.

        Centraliza a construção do grafo de dependências.
        Em testes, instancie diretamente com mocks injetados.

        Args:
            cfg: configuração validada
            client: cliente HTTP já inicializado

        Returns:
            Pipeline pronto para execução
        """
        return cls(
            cfg=cfg,
            client=client,
            downloader=Downloader(
                client=client,
                pasta_download=cfg.pasta_download,
                chunk_size=cfg.chunk_size,
                timeout_total=cfg.timeout_total,
                timeout_sem_progresso=cfg.timeout_sem_progresso,
            ),
            validator=Validator(
                tamanho_minimo=cfg.tamanho_minimo_zip
            ),
            extractor=Extractor(
                pasta_extraidos=cfg.pasta_extraidos
            ),
        )

    def executar(self) -> SumarioPipeline:
        """
        Executa o pipeline completo.

        Etapas:
            1. Verifica espaço em disco
            2. Lista arquivos disponíveis no servidor
            3. Filtra arquivos já processados
            4. Executa download + extração em paralelo
            5. Limpa arquivos .done
            6. Retorna sumário

        Returns:
            SumarioPipeline com resultado de cada arquivo

        Raises:
            InsufficientDiskSpaceError: espaço insuficiente antes de iniciar
            ListingError: falha ao listar arquivos no servidor
            CompetenciaNotFoundError: competência não publicada
        """
        inicio = time.monotonic()

        sumario = SumarioPipeline(competencia=self._cfg.competencia)

        logger.info("=" * 60)
        logger.info("INÍCIO DO PIPELINE")
        logger.info(f"Competência : {self._cfg.competencia}")
        logger.info(f"Prefixos    : {self._cfg.prefixos}")
        logger.info(f"Workers     : {self._cfg.max_workers}")
        logger.info(f"Download    : {self._cfg.pasta_download}")
        logger.info(f"Extração    : {self._cfg.pasta_extraidos}")
        logger.info("=" * 60)

        # etapa 1 — verifica espaço antes de qualquer operação
        self._validator.verificar_espaco_disco(
            caminho=self._cfg.pasta_download,
            espaco_minimo_gb=self._cfg.espaco_minimo_gb
        )

        # etapa 2 — lista arquivos disponíveis
        try:
            todos = self._client.listar_arquivos(self._cfg.competencia)
        except CompetenciaNotFoundError:
            anterior = self._cfg.competencia_anterior()
            logger.error(
                f"Competência {self._cfg.competencia} não encontrada. "
                f"Tente: --competencia {anterior}"
            )
            raise

        # filtra pelos prefixos configurados
        arquivos = [
            a for a in todos
            if any(
                a.nome.lower().startswith(p.lower())
                for p in self._cfg.prefixos
            )
        ]

        if not arquivos:
            logger.warning("Nenhum arquivo encontrado para os prefixos configurados.")
            return sumario

        sumario.total = len(arquivos)
        logger.info(f"{len(arquivos)} arquivo(s) filtrado(s)")

        # etapa 3 — separa já processados de pendentes
        pendentes = []
        for arq in arquivos:
            if self._extractor.ja_extraido(arq.nome):
                logger.info(f"[SKIP] {arq.nome} — já processado")
                sumario.pulados += 1
                sumario.resultados.append(
                    ResultadoArquivo(nome=arq.nome, sucesso=True)
                )
            else:
                pendentes.append(arq)

        if not pendentes:
            logger.info("Todos os arquivos já estão processados.")
        else:
            # etapa 4 — download + extração com fila produtor/consumidor
            self._executar_com_fila(pendentes, sumario)

        # etapa 5 — limpa arquivos .done
        removidos = self._extractor.limpar_done_files()
        if removidos > 0:
            logger.info(f"[LIMPEZA] {removidos} arquivo(s) .done removidos")

        sumario.duracao_total = time.monotonic() - inicio
        sumario.logar()

        return sumario

    def _executar_com_fila(
        self,
        arquivos: list[ArquivoInfo],
        sumario: SumarioPipeline
    ) -> None:
        """
        Executa download e extração com fila produtor/consumidor.

        Arquitetura:
            - Pool de download (max_workers): baixa arquivos em paralelo
              e coloca paths na fila quando completos
            - Pool de extração (1 worker): consome da fila e extrai
              sequencialmente — I/O de disco é sequencial por natureza

        A fila desacopla download e extração — enquanto um arquivo
        extrai, outros continuam sendo baixados, maximizando uso
        simultâneo de rede e disco.

        Sentinel value:
            None é inserido na fila pelo produtor ao final para
            sinalizar ao consumidor que não há mais items — padrão
            clássico de terminação de fila produtor/consumidor.

        Args:
            arquivos: lista de ArquivoInfo a processar
            sumario: objeto de sumário a ser atualizado
        """
        # fila com capacidade limitada — evita download de todos os arquivos
        # antes de qualquer extração (controle de memória e disco)
        fila_extracao: queue.Queue = queue.Queue(maxsize=self._cfg.max_workers + 1)

        resultados: dict[str, ResultadoArquivo] = {}

        def producer() -> None:
            """
            Worker de download — produz paths na fila.

            Executa downloads em paralelo com ThreadPoolExecutor.
            Coloca (nome, caminho, arquivos_internos) na fila
            quando download + validação completam com sucesso.
            Coloca (nome, None, None) em caso de falha para
            sinalizar ao consumidor que esse arquivo não será extraído.
            """
            with ThreadPoolExecutor(max_workers=self._cfg.max_workers) as pool:
                futures = {
                    pool.submit(self._baixar_e_validar, arq): arq
                    for arq in arquivos
                }

                for future in as_completed(futures):
                    arq = futures[future]
                    try:
                        resultado = future.result()
                        resultados[arq.nome] = resultado
                        if resultado.sucesso:
                            # sinaliza ao consumidor que esse arquivo está pronto
                            fila_extracao.put((
                                arq.nome,
                                self._cfg.pasta_download / arq.nome,
                                resultado._arquivos_internos
                            ))
                        else:
                            # sinaliza falha — consumidor pula esse arquivo
                            fila_extracao.put((arq.nome, None, None))
                    except Exception as e:
                        logger.error(f"[ERRO INESPERADO] {arq.nome}: {e}")
                        resultados[arq.nome] = ResultadoArquivo(
                            nome=arq.nome,
                            sucesso=False,
                            erro=str(e),
                            etapa_falha="download"
                        )
                        fila_extracao.put((arq.nome, None, None))

            # sentinel — sinaliza ao consumidor que não há mais itens
            fila_extracao.put(None)

        def consumer() -> None:
            """
            Worker de extração — consome paths da fila.

            Extrai sequencialmente — 1 arquivo por vez.
            Termina quando recebe o sentinel (None).
            """
            while True:
                item = fila_extracao.get()

                # sentinel recebido — producer terminou
                if item is None:
                    break

                nome, caminho, arquivos_internos = item

                # falha no download — pula extração
                if caminho is None:
                    continue

                resultado = self._extrair(nome, caminho, arquivos_internos)

                # merge com resultado de download existente
                if nome in resultados:
                    if not resultado.sucesso:
                        resultados[nome].sucesso = False
                        resultados[nome].erro = resultado.erro
                        resultados[nome].etapa_falha = resultado.etapa_falha
                else:
                    resultados[nome] = resultado

                fila_extracao.task_done()

        # executa producer e consumer em threads separadas
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_producer = executor.submit(producer)
            future_consumer = executor.submit(consumer)

            # aguarda ambos completarem
            future_producer.result()
            future_consumer.result()

        # atualiza sumário com resultados
        for resultado in resultados.values():
            sumario.resultados.append(resultado)
            if resultado.sucesso:
                sumario.sucessos += 1
            else:
                sumario.falhas += 1

    def _baixar_e_validar(self, arq: ArquivoInfo) -> "ResultadoArquivo":
        """
        Baixa e valida um arquivo — executado no pool de download.

        Separa download e validação do resto do pipeline para
        que possam rodar em paralelo no ThreadPoolExecutor.

        Armazena arquivos_internos no resultado para evitar
        reabrir o ZIP na etapa de extração.

        Args:
            arq: metadados do arquivo a baixar

        Returns:
            ResultadoArquivo com status e métricas
        """
        inicio = time.monotonic()
        resultado = ResultadoArquivo(nome=arq.nome)
        resultado._arquivos_internos = []  # armazena para o extractor

        try:
            # download
            logger.info(f"[DOWNLOAD] {arq.nome}")
            metrics = self._downloader.baixar(
                competencia=self._cfg.competencia,
                nome=arq.nome
            )
            resultado.metrics = metrics
            logger.info(f"[DOWNLOAD OK] {metrics}")

            # validação
            logger.info(f"[VALIDANDO] {arq.nome}")
            caminho = self._cfg.pasta_download / arq.nome
            arquivos_internos = self._validator.validar(arq.nome, caminho)
            resultado._arquivos_internos = arquivos_internos
            resultado.sucesso = True
            logger.info(f"[VALIDAÇÃO OK] {arq.nome}")

        except ValidationError as e:
            resultado.sucesso = False
            resultado.erro = str(e)
            resultado.etapa_falha = "validação"
            # preserva ZIP corrompido para inspeção manual
            self._preservar_corrompido(arq.nome)
            logger.error(f"[VALIDAÇÃO FALHOU] {e}")

        except DownloadError as e:
            resultado.sucesso = False
            resultado.erro = str(e)
            resultado.etapa_falha = "download"
            logger.error(f"[DOWNLOAD FALHOU] {e}")

        except RFBError as e:
            resultado.sucesso = False
            resultado.erro = str(e)
            resultado.etapa_falha = "download"
            logger.error(f"[ERRO] {e}")

        resultado.duracao_total = time.monotonic() - inicio
        return resultado

    def _extrair(
        self,
        nome: str,
        caminho: Path,
        arquivos_internos: list[str]
    ) -> ResultadoArquivo:
        """
        Extrai um arquivo — executado no consumer (pool de extração).

        Args:
            nome: nome do ZIP
            caminho: path físico do ZIP
            arquivos_internos: lista de arquivos internos do ZIP

        Returns:
            ResultadoArquivo com status da extração
        """
        inicio = time.monotonic()
        resultado = ResultadoArquivo(nome=nome)

        try:
            logger.info(f"[EXTRAÇÃO] {nome}")
            csv_path = self._extractor.extrair(
                nome=nome,
                caminho=caminho,
                arquivos_internos=arquivos_internos
            )

            # remove ZIP após extração bem-sucedida
            if caminho.exists():
                caminho.unlink()
                logger.info(f"[LIMPEZA] ZIP removido: {nome}")

            resultado.sucesso = True
            logger.info(f"[EXTRAÇÃO OK] {nome} → {csv_path.name}")

        except (ExtractionError, RenameError) as e:
            resultado.sucesso = False
            resultado.erro = str(e)
            resultado.etapa_falha = "extração"
            logger.error(f"[EXTRAÇÃO FALHOU] {e}")

        except RFBError as e:
            resultado.sucesso = False
            resultado.erro = str(e)
            resultado.etapa_falha = "extração"
            logger.error(f"[ERRO] {e}")

        resultado.duracao_total = time.monotonic() - inicio
        return resultado

    def _preservar_corrompido(self, nome: str) -> None:
        """
        Renomeia arquivo corrompido para prefixo CORROMPIDO_.

        Preserva o arquivo para inspeção manual em vez de deletar —
        permite diagnóstico posterior sem precisar re-baixar.

        Args:
            nome: nome do ZIP corrompido
        """
        caminho = self._cfg.pasta_download / nome
        if not caminho.exists():
            return

        destino = caminho.with_name(f"CORROMPIDO_{nome}")
        try:
            caminho.rename(destino)
            logger.warning(f"[CORROMPIDO] {nome} → {destino.name}")
        except OSError as e:
            logger.error(f"[ERRO] Não foi possível renomear {nome}: {e}")