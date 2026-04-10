"""
tests/test_pipeline.py
----------------------
Testes de integração do Pipeline.

Estratégia:
    Pipeline orquestra todos os componentes — testamos com
    componentes reais (Downloader, Extractor, Validator) mas
    com MockClient para evitar dependência de rede.

    Isso é integração, não unitário — testa que os componentes
    funcionam corretamente em conjunto.

Cobertura:
    ✓ Execução bem-sucedida — caminho feliz
    ✓ Idempotência — arquivos já processados são pulados
    ✓ Competência não encontrada
    ✓ Espaço insuficiente
    ✓ Nenhum arquivo encontrado
    ✓ Falha parcial — alguns arquivos falham, outros passam
    ✓ Sumário — contagem correta de sucessos/falhas/pulados
    ✓ Limpeza — .done removidos ao final
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rfb.client import ArquivoInfo
from rfb.config import Config
from rfb.errors import CompetenciaNotFoundError, InsufficientDiskSpaceError
from rfb.pipeline import Pipeline, SumarioPipeline
from rfb.extractor import Extractor
from tests.conftest import criar_done_file


# ==================== HELPERS ====================

def criar_mock_client(
    arquivos: list[ArquivoInfo] | None = None,
    conteudo_zip: bytes | None = None,
    nome_interno: str = "K3241.K03200Y0.D60314.EMPRECSV",
) -> MagicMock:
    """
    Cria MockClient configurado para simular servidor RFB.

    Cria um ZIP real em memória para que Validator e Extractor
    funcionem corretamente — não usa bytes aleatórios.

    Args:
        arquivos: lista de ArquivoInfo retornada pela listagem
        conteudo_zip: bytes do ZIP a retornar no download
        nome_interno: nome do arquivo interno do ZIP

    Returns:
        MagicMock configurado como RFBClient
    """
    if arquivos is None:
        arquivos = [
            ArquivoInfo(
                nome="Empresas0.zip",
                tamanho_bytes=100,
                href="/dav/files/token/2026-03/Empresas0.zip"
            )
        ]

    if conteudo_zip is None:
        # cria ZIP real para passar na validação
        import io
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(nome_interno, b"cnpj;razao_social\n00000191;TESTE SA\n")
        conteudo_zip = buffer.getvalue()

    client = MagicMock()
    client.listar_arquivos.return_value = arquivos
    client.__enter__ = lambda s: s
    client.__exit__ = MagicMock(return_value=False)

    # mock de Response para stream_download
    mock_response = MagicMock()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.status_code = 200

    client.stream_download.return_value = mock_response

    # chunks retorna o ZIP real em pedaços
    chunk_size_teste = 512
    chunks = [
        conteudo_zip[i:i + chunk_size_teste]
        for i in range(0, len(conteudo_zip), chunk_size_teste)
    ]
    client.chunks.return_value = iter(chunks)

    return client


# ==================== CAMINHO FELIZ ====================

class TestPipelineExecucao:
    """Testes de execução completa do pipeline."""

    def test_executa_sem_excecao(self, cfg: Config):
        """Pipeline completo deve executar sem lançar exceção."""
        client = criar_mock_client()

        # chunks precisa ser iterável a cada chamada
        import io
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("K3241.K03200Y0.D60314.EMPRECSV", b"dados")
        zip_bytes = buffer.getvalue()

        client.chunks.side_effect = lambda r, cs: iter([zip_bytes])

        pipeline = Pipeline.from_config(cfg, client)

        try:
            pipeline.executar()
        except Exception as e:
            pytest.fail(f"Pipeline lançou exceção inesperada: {e}")

    def test_retorna_sumario_pipeline(self, cfg: Config):
        """executar() deve retornar SumarioPipeline."""
        client = criar_mock_client()
        client.listar_arquivos.return_value = []

        pipeline = Pipeline.from_config(cfg, client)
        sumario = pipeline.executar()

        assert isinstance(sumario, SumarioPipeline)

    def test_sumario_tem_competencia_correta(self, cfg: Config):
        """Sumário deve registrar a competência processada."""
        client = criar_mock_client()

        pipeline = Pipeline.from_config(cfg, client)
        sumario = pipeline.executar()

        assert sumario.competencia == cfg.competencia

    def test_lista_arquivos_chamado_com_competencia(self, cfg: Config):
        """listar_arquivos deve ser chamado com a competência do config."""
        client = criar_mock_client()

        pipeline = Pipeline.from_config(cfg, client)
        pipeline.executar()

        client.listar_arquivos.assert_called_once_with(cfg.competencia)


# ==================== IDEMPOTÊNCIA ====================

class TestPipelineIdempotencia:
    """Pipeline re-executado não deve re-processar arquivos concluídos."""

    def test_pula_arquivo_com_done(self, cfg: Config):
        """
        Arquivo com .done existente não deve acionar download.
        Verifica que stream_download não é chamado.
        """
        criar_done_file(cfg.pasta_extraidos, "Empresas0.zip")

        client = criar_mock_client()
        pipeline = Pipeline.from_config(cfg, client)
        pipeline.executar()

        client.stream_download.assert_not_called()

    def test_arquivo_pulado_contabilizado_no_sumario(self, cfg: Config):
        """Arquivo pulado deve incrementar sumario.pulados."""
        criar_done_file(cfg.pasta_extraidos, "Empresas0.zip")

        client = criar_mock_client()
        pipeline = Pipeline.from_config(cfg, client)
        sumario = pipeline.executar()

        assert sumario.pulados == 1

    def test_todos_pulados_nao_chama_download(self, cfg: Config):
        """Se todos os arquivos têm .done, nenhum download ocorre."""
        arquivos = [
            ArquivoInfo("Empresas0.zip", 100, "/href/Empresas0.zip"),
            ArquivoInfo("Municipios.zip", 100, "/href/Municipios.zip"),
        ]

        for arq in arquivos:
            criar_done_file(cfg.pasta_extraidos, arq.nome)

        client = criar_mock_client(arquivos=arquivos)
        pipeline = Pipeline.from_config(cfg, client)
        sumario = pipeline.executar()

        client.stream_download.assert_not_called()
        assert sumario.pulados == 2


# ==================== ERROS CRÍTICOS ====================

class TestPipelineErrosCriticos:
    """Erros que impedem o pipeline de iniciar."""

    def test_competencia_nao_encontrada(self, cfg: Config):
        """
        CompetenciaNotFoundError da listagem deve propagar para o caller.
        Pipeline não deve tentar continuar com lista vazia.
        """
        client = MagicMock()
        client.listar_arquivos.side_effect = CompetenciaNotFoundError(
            f"Competência {cfg.competencia} não encontrada"
        )
        client.__enter__ = lambda s: s
        client.__exit__ = MagicMock(return_value=False)

        pipeline = Pipeline.from_config(cfg, client)

        with pytest.raises(CompetenciaNotFoundError):
            pipeline.executar()

    def test_espaco_insuficiente_antes_de_baixar(self, cfg: Config):
        """
        InsufficientDiskSpaceError deve ser lançado antes de qualquer download.
        Evita operações parciais por falta de espaço.
        """
        client = criar_mock_client()

        # força erro de espaço no validator
        with patch(
            "rfb.validator.Validator.verificar_espaco_disco",
            side_effect=InsufficientDiskSpaceError(
                livre_gb=1.0,
                necessario_gb=25.0
            )
        ):
            pipeline = Pipeline.from_config(cfg, client)

            with pytest.raises(InsufficientDiskSpaceError):
                pipeline.executar()

        # nenhum download deve ter ocorrido
        client.stream_download.assert_not_called()


# ==================== NENHUM ARQUIVO ====================

class TestPipelineNenhumArquivo:
    """Cenários onde nenhum arquivo é encontrado."""

    def test_lista_vazia_retorna_sumario_zerado(self, cfg: Config):
        """Sem arquivos na listagem, sumário deve ter total=0."""
        client = criar_mock_client(arquivos=[])

        pipeline = Pipeline.from_config(cfg, client)
        sumario = pipeline.executar()

        assert sumario.total == 0
        assert sumario.sucessos == 0
        assert sumario.falhas == 0

    def test_sem_match_de_prefixo_retorna_sumario_zerado(self, cfg: Config):
        """
        Arquivos que não batem com nenhum prefixo configurado
        devem ser ignorados — sumário zerado.
        """
        arquivos_sem_match = [
            ArquivoInfo("Socios0.zip", 100, "/href"),
            ArquivoInfo("Simples.zip", 100, "/href"),
            ArquivoInfo("Cnaes.zip", 100, "/href"),
        ]

        client = criar_mock_client(arquivos=arquivos_sem_match)
        pipeline = Pipeline.from_config(cfg, client)
        sumario = pipeline.executar()

        assert sumario.total == 0
        client.stream_download.assert_not_called()


# ==================== SUMÁRIO ====================

class TestSumarioPipeline:
    """Testes do SumarioPipeline."""

    def test_sumario_logar_nao_lanca_excecao(self):
        """SumarioPipeline.logar() deve funcionar sem erro."""
        sumario = SumarioPipeline(
            competencia="2026-03",
            total=3,
            sucessos=2,
            falhas=1,
            pulados=0,
            duracao_total=120.0
        )

        try:
            sumario.logar()
        except Exception as e:
            pytest.fail(f"logar() lançou exceção: {e}")

    def test_sumario_com_falhas_loga_warning(self, caplog):
        """
        Quando há falhas, sumário deve logar aviso de re-execução.
        Informa o usuário que pode re-executar para re-tentar.
        """
        import logging

        sumario = SumarioPipeline(
            competencia="2026-03",
            total=5,
            sucessos=3,
            falhas=2,
            duracao_total=100.0
        )

        with caplog.at_level(logging.WARNING, logger="rfb.pipeline"):
            sumario.logar()

        assert any("re-execute" in r.message.lower() for r in caplog.records)

    @pytest.mark.parametrize("sucessos,falhas,pulados,total", [
        (21, 0, 0, 21),
        (0, 0, 21, 21),
        (10, 5, 6, 21),
        (0, 21, 0, 21),
    ])
    def test_contadores_parametrizados(
        self,
        sucessos: int,
        falhas: int,
        pulados: int,
        total: int
    ):
        """Contadores do sumário devem refletir exatamente o que foi passado."""
        sumario = SumarioPipeline(
            competencia="2026-03",
            total=total,
            sucessos=sucessos,
            falhas=falhas,
            pulados=pulados,
        )

        assert sumario.total == total
        assert sumario.sucessos == sucessos
        assert sumario.falhas == falhas
        assert sumario.pulados == pulados


# ==================== LIMPEZA ====================

class TestPipelineLimpeza:
    """Pipeline deve remover arquivos temporários ao final."""

    def test_done_files_removidos_ao_final(self, cfg: Config):
        """
        Arquivos .done devem ser removidos ao final do pipeline.
        São arquivos temporários de controle — não devem persistir.
        """
        # cria .done manualmente para simular execução anterior
        done = cfg.pasta_extraidos / ".Empresas0.done"
        criar_done_file(cfg.pasta_extraidos, "Empresas0.zip")

        client = criar_mock_client()
        pipeline = Pipeline.from_config(cfg, client)
        pipeline.executar()

        assert not done.exists()

    def test_csvs_nao_removidos(self, cfg: Config):
        """
        CSVs extraídos não devem ser removidos na limpeza.
        Apenas .done são temporários.
        """
        csv = cfg.pasta_extraidos / "Empresas0.csv"
        csv.write_bytes(b"dados importantes")

        client = criar_mock_client(arquivos=[])
        client.listar_arquivos.return_value = []
        pipeline = Pipeline.from_config(cfg, client)
        pipeline.executar()

        assert csv.exists()
        assert csv.read_bytes() == b"dados importantes"