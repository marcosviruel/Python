"""
tests/test_extractor.py
-----------------------
Testes unitários e de integração do Extractor.

Cobertura:
    ✓ Extração bem-sucedida — caminho feliz
    ✓ Renomeação correta baseada no ZIP de origem
    ✓ Idempotência — arquivo já extraído é pulado
    ✓ ZIP corrompido durante extração
    ✓ Erro de I/O durante extração
    ✓ Renomeação falha — arquivo interno não encontrado
    ✓ Limpeza de arquivos .done
    ✓ ja_extraido() — detecção por arquivo .done
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from rfb.extractor import Extractor
from rfb.errors import ExtractionError, RenameError


# ==================== FIXTURE LOCAL ====================

@pytest.fixture
def extractor(tmp_extraidos: Path) -> Extractor:
    """Extractor apontando para diretório temporário de testes."""
    return Extractor(pasta_extraidos=tmp_extraidos)


# ==================== HELPERS ====================

def criar_zip(pasta: Path, nome_zip: str, arquivos: dict[str, bytes]) -> Path:
    """
    Cria um ZIP com arquivos definidos em dict {nome_interno: conteudo}.

    Helper centralizado para evitar repetição de criação de ZIPs
    em cada teste — mantém os testes focados no comportamento,
    não na preparação de dados.

    Args:
        pasta: diretório onde o ZIP será criado
        nome_zip: nome do arquivo ZIP (ex: "Empresas0.zip")
        arquivos: dict mapeando nome interno para conteúdo em bytes

    Returns:
        Path do ZIP criado
    """
    caminho = pasta / nome_zip
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome, conteudo)
    return caminho


# ==================== CAMINHO FELIZ ====================

class TestExtracaoCompleta:
    """Extração bem-sucedida com renomeação correta."""

    def test_cria_csv_com_nome_correto(
        self, extractor: Extractor, tmp_download: Path, tmp_extraidos: Path
    ):
        """
        Após extração de Empresas0.zip, deve existir Empresas0.csv
        no diretório de extração — não o nome interno do mainframe.
        """
        caminho = criar_zip(
            tmp_download,
            "Empresas0.zip",
            {"K3241.K03200Y0.D60314.EMPRECSV": b"cnpj;razao_social\n"}
        )

        extractor.extrair(
            nome="Empresas0.zip",
            caminho=caminho,
            arquivos_internos=["K3241.K03200Y0.D60314.EMPRECSV"]
        )

        assert (tmp_extraidos / "Empresas0.csv").exists()

    def test_nao_mantém_nome_interno_mainframe(
        self, extractor: Extractor, tmp_download: Path, tmp_extraidos: Path
    ):
        """
        Nome interno do mainframe não deve existir após renomeação.
        Garante que a renomeação realmente ocorreu.
        """
        caminho = criar_zip(
            tmp_download,
            "Empresas0.zip",
            {"K3241.K03200Y0.D60314.EMPRECSV": b"dados"}
        )

        extractor.extrair(
            nome="Empresas0.zip",
            caminho=caminho,
            arquivos_internos=["K3241.K03200Y0.D60314.EMPRECSV"]
        )

        assert not (tmp_extraidos / "K3241.K03200Y0.D60314.EMPRECSV").exists()

    def test_retorna_path_do_csv(
        self, extractor: Extractor, tmp_download: Path, tmp_extraidos: Path
    ):
        """extrair() deve retornar o Path do CSV final."""
        caminho = criar_zip(
            tmp_download,
            "Municipios.zip",
            {"F.K03200$Z.D60314.MUNICCSV": b"cod;nome\n"}
        )

        resultado = extractor.extrair(
            nome="Municipios.zip",
            caminho=caminho,
            arquivos_internos=["F.K03200$Z.D60314.MUNICCSV"]
        )

        assert resultado == tmp_extraidos / "Municipios.csv"

    def test_conteudo_csv_preservado(
        self, extractor: Extractor, tmp_download: Path, tmp_extraidos: Path
    ):
        """Conteúdo do arquivo extraído deve ser idêntico ao original."""
        conteudo = b"00000000000191;EMPRESA TESTE SA;SP\n"
        caminho = criar_zip(
            tmp_download,
            "Empresas0.zip",
            {"K3241.K03200Y0.D60314.EMPRECSV": conteudo}
        )

        extractor.extrair(
            nome="Empresas0.zip",
            caminho=caminho,
            arquivos_internos=["K3241.K03200Y0.D60314.EMPRECSV"]
        )

        csv = tmp_extraidos / "Empresas0.csv"
        assert csv.read_bytes() == conteudo

    def test_cria_done_file(
        self, extractor: Extractor, tmp_download: Path, tmp_extraidos: Path
    ):
        """
        Arquivo .done deve ser criado após extração bem-sucedida.
        É a base do mecanismo de idempotência do pipeline.
        """
        caminho = criar_zip(
            tmp_download,
            "Empresas0.zip",
            {"K3241.K03200Y0.D60314.EMPRECSV": b"dados"}
        )

        extractor.extrair(
            nome="Empresas0.zip",
            caminho=caminho,
            arquivos_internos=["K3241.K03200Y0.D60314.EMPRECSV"]
        )

        assert (tmp_extraidos / ".Empresas0.done").exists()

    def test_done_criado_apos_renomeacao(
        self, extractor: Extractor, tmp_download: Path, tmp_extraidos: Path
    ):
        """
        .done deve ser criado APÓS a renomeação — não antes.
        Se renomeação falhar, .done não deve existir.
        Garante atomicidade: ou tudo completa ou nada é marcado.
        """
        caminho = criar_zip(
            tmp_download,
            "Empresas0.zip",
            {"K3241.K03200Y0.D60314.EMPRECSV": b"dados"}
        )

        # força falha na renomeação
        with patch.object(extractor, "_renomear", side_effect=RenameError(
            arquivo="Empresas0.zip",
            destino="Empresas0.csv",
            motivo="erro simulado"
        )):
            with pytest.raises(RenameError):
                extractor.extrair(
                    nome="Empresas0.zip",
                    caminho=caminho,
                    arquivos_internos=["K3241.K03200Y0.D60314.EMPRECSV"]
                )

        # .done não deve existir — extração não completou
        assert not (tmp_extraidos / ".Empresas0.done").exists()


# ==================== IDEMPOTÊNCIA ====================

class TestIdempotencia:
    """Re-execução não deve re-extrair arquivos já processados."""

    def test_pula_se_done_existe(
        self, extractor: Extractor, tmp_download: Path, tmp_extraidos: Path
    ):
        """
        Se .done existe, extrair() deve retornar sem re-extrair.
        Crítico para re-execuções após interrupção parcial.
        """
        # cria .done manualmente — simula execução anterior
        done = tmp_extraidos / ".Empresas0.done"
        done.touch()

        caminho = criar_zip(
            tmp_download,
            "Empresas0.zip",
            {"K3241.K03200Y0.D60314.EMPRECSV": b"dados"}
        )

        # não deve lançar exceção nem re-extrair
        resultado = extractor.extrair(
            nome="Empresas0.zip",
            caminho=caminho,
            arquivos_internos=["K3241.K03200Y0.D60314.EMPRECSV"]
        )

        # retorna path esperado mesmo sem re-extrair
        assert resultado == tmp_extraidos / "Empresas0.csv"

    def test_nao_chama_zipfile_se_done_existe(
        self, extractor: Extractor, tmp_download: Path, tmp_extraidos: Path
    ):
        """
        Com .done existente, ZipFile não deve ser aberto.
        Verifica que o skip é real — não apenas silencioso.
        """
        done = tmp_extraidos / ".Empresas0.done"
        done.touch()

        caminho = tmp_download / "Empresas0.zip"
        caminho.write_bytes(b"nao importa")

        with patch("zipfile.ZipFile") as mock_zip:
            extractor.extrair(
                nome="Empresas0.zip",
                caminho=caminho,
                arquivos_internos=["qualquer"]
            )

        mock_zip.assert_not_called()

    def test_ja_extraido_retorna_true_com_done(
        self, extractor: Extractor, tmp_extraidos: Path
    ):
        done = tmp_extraidos / ".Empresas0.done"
        done.touch()

        assert extractor.ja_extraido("Empresas0.zip") is True

    def test_ja_extraido_retorna_false_sem_done(
        self, extractor: Extractor
    ):
        assert extractor.ja_extraido("Empresas0.zip") is False


# ==================== ERROS DE EXTRAÇÃO ====================

class TestErrosExtracao:
    """Falhas durante a extração do ZIP."""

    def test_bad_zip_file_lanca_extraction_error(
        self, extractor: Extractor, tmp_download: Path
    ):
        """
        ZIP que passa na validação mas corrompe durante extração
        deve lançar ExtractionError — não BadZipFile nativo.
        Encapsula erro no domínio do pipeline.
        """
        # arquivo que não é ZIP válido
        caminho = tmp_download / "Empresas0.zip"
        caminho.write_bytes(b"nao e um zip valido")

        with pytest.raises(ExtractionError):
            extractor.extrair(
                nome="Empresas0.zip",
                caminho=caminho,
                arquivos_internos=["K3241.K03200Y0.D60314.EMPRECSV"]
            )

    def test_extraction_error_nao_cria_done(
        self, extractor: Extractor, tmp_download: Path, tmp_extraidos: Path
    ):
        """
        Falha na extração não deve criar .done —
        permite re-tentativa na próxima execução.
        """
        caminho = tmp_download / "Empresas0.zip"
        caminho.write_bytes(b"invalido")

        with pytest.raises(ExtractionError):
            extractor.extrair(
                nome="Empresas0.zip",
                caminho=caminho,
                arquivos_internos=["arquivo"]
            )

        assert not (tmp_extraidos / ".Empresas0.done").exists()

    def test_os_error_lanca_extraction_error(
        self, extractor: Extractor, tmp_download: Path
    ):
        """
        Erro de I/O durante extração (disco cheio, permissão)
        deve lançar ExtractionError com mensagem clara.
        """
        caminho = criar_zip(
            tmp_download,
            "Empresas0.zip",
            {"arquivo.csv": b"dados"}
        )

        with patch("zipfile.ZipFile") as mock_zip:
            mock_zip.return_value.__enter__.side_effect = OSError("disco cheio")

            with pytest.raises(ExtractionError, match="I/O"):
                extractor.extrair(
                    nome="Empresas0.zip",
                    caminho=caminho,
                    arquivos_internos=["arquivo.csv"]
                )


# ==================== ERROS DE RENOMEAÇÃO ====================

class TestErrosRenomeacao:
    """Falhas durante renomeação do arquivo extraído."""

    def test_arquivo_interno_nao_encontrado_lanca_rename_error(
        self, extractor: Extractor, tmp_download: Path
    ):
        """
        Se o arquivo interno do ZIP não for encontrado no disco
        após extração, deve lançar RenameError.

        Pode acontecer se o nome interno mudou entre versões da RFB.
        """
        caminho = criar_zip(
            tmp_download,
            "Empresas0.zip",
            {"K3241.K03200Y0.D60314.EMPRECSV": b"dados"}
        )

        # passa nome interno errado — não vai encontrar no disco
        with pytest.raises(RenameError):
            extractor.extrair(
                nome="Empresas0.zip",
                caminho=caminho,
                arquivos_internos=["NOME_QUE_NAO_EXISTE.CSV"]
            )

    def test_rename_error_nao_cria_done(
        self, extractor: Extractor, tmp_download: Path, tmp_extraidos: Path
    ):
        """
        RenameError não deve criar .done —
        estado inconsistente deve ser detectável na próxima execução.
        """
        caminho = criar_zip(
            tmp_download,
            "Empresas0.zip",
            {"K3241.K03200Y0.D60314.EMPRECSV": b"dados"}
        )

        with pytest.raises(RenameError):
            extractor.extrair(
                nome="Empresas0.zip",
                caminho=caminho,
                arquivos_internos=["NOME_ERRADO.CSV"]
            )

        assert not (tmp_extraidos / ".Empresas0.done").exists()

    def test_destino_ja_existe_nao_lanca_erro(
        self, extractor: Extractor, tmp_download: Path, tmp_extraidos: Path
    ):
        """
        Se CSV de destino já existe (de extração anterior sem .done),
        renomeação deve ser pulada sem erro — comportamento idempotente.
        """
        # cria CSV destino previamente
        csv_existente = tmp_extraidos / "Empresas0.csv"
        csv_existente.write_bytes(b"dados anteriores")

        caminho = criar_zip(
            tmp_download,
            "Empresas0.zip",
            {"K3241.K03200Y0.D60314.EMPRECSV": b"dados novos"}
        )

        # não deve lançar erro
        extractor.extrair(
            nome="Empresas0.zip",
            caminho=caminho,
            arquivos_internos=["K3241.K03200Y0.D60314.EMPRECSV"]
        )

        # conteúdo anterior preservado — não sobrescreveu
        assert csv_existente.read_bytes() == b"dados anteriores"


# ==================== LIMPEZA ====================

class TestLimpeza:
    """Remoção de arquivos .done ao final do pipeline."""

    def test_remove_todos_done_files(
        self, extractor: Extractor, tmp_extraidos: Path
    ):
        """limpar_done_files() deve remover todos os .done do diretório."""
        # cria múltiplos .done
        for nome in ["Empresas0", "Empresas1", "Municipios"]:
            (tmp_extraidos / f".{nome}.done").touch()

        removidos = extractor.limpar_done_files()

        assert removidos == 3
        assert list(tmp_extraidos.glob(".*.done")) == []

    def test_retorna_zero_sem_done_files(
        self, extractor: Extractor, tmp_extraidos: Path
    ):
        """Sem .done files, deve retornar 0 sem erro."""
        removidos = extractor.limpar_done_files()
        assert removidos == 0

    def test_nao_remove_csv(
        self, extractor: Extractor, tmp_extraidos: Path
    ):
        """limpar_done_files() não deve remover CSVs — apenas .done."""
        csv = tmp_extraidos / "Empresas0.csv"
        csv.write_bytes(b"dados")
        done = tmp_extraidos / ".Empresas0.done"
        done.touch()

        extractor.limpar_done_files()

        # CSV deve continuar existindo
        assert csv.exists()
        # .done deve ter sido removido
        assert not done.exists()


# ==================== EDGE CASES ====================

class TestEdgeCases:
    """Casos extremos e situações incomuns."""

    def test_zip_com_multiplos_arquivos_internos(
        self, extractor: Extractor, tmp_download: Path, tmp_extraidos: Path
    ):
        """
        ZIP com múltiplos arquivos internos — apenas o que bate
        com arquivos_internos deve ser renomeado para .csv.
        """
        caminho = criar_zip(
            tmp_download,
            "Empresas0.zip",
            {
                "K3241.K03200Y0.D60314.EMPRECSV": b"principal",
                "LEIAME.TXT": b"instrucoes",
            }
        )

        extractor.extrair(
            nome="Empresas0.zip",
            caminho=caminho,
            arquivos_internos=[
                "K3241.K03200Y0.D60314.EMPRECSV",
                "LEIAME.TXT"
            ]
        )

        # arquivo principal renomeado corretamente
        assert (tmp_extraidos / "Empresas0.csv").exists()

    @pytest.mark.parametrize("nome_zip,nome_csv", [
        ("Empresas0.zip", "Empresas0.csv"),
        ("Empresas9.zip", "Empresas9.csv"),
        ("Estabelecimentos0.zip", "Estabelecimentos0.csv"),
        ("Municipios.zip", "Municipios.csv"),
    ])
    def test_nomenclatura_todos_prefixos(
        self,
        extractor: Extractor,
        tmp_download: Path,
        tmp_extraidos: Path,
        nome_zip: str,
        nome_csv: str,
    ):
        """
        Nomenclatura correta para todos os tipos de arquivo da RFB.
        Garante que a renomeação funciona para todos os prefixos configurados.
        """
        nome_interno = f"ARQUIVO_INTERNO_{nome_zip.replace('.zip', '')}"
        caminho = criar_zip(
            tmp_download,
            nome_zip,
            {nome_interno: b"dados"}
        )

        extractor.extrair(
            nome=nome_zip,
            caminho=caminho,
            arquivos_internos=[nome_interno]
        )

        assert (tmp_extraidos / nome_csv).exists()