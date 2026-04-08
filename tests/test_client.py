"""
tests/test_client.py
--------------------
Testes unitários do RFBClient.

Estratégia:
    RFBClient faz chamadas HTTP reais — todos os testes usam
    `responses` (biblioteca de mock HTTP) ou `unittest.mock.patch`
    para interceptar requests sem depender de rede.

    Por que mockar no nível do requests e não do client?
    Porque queremos testar o comportamento do RFBClient em si —
    como ele interpreta respostas HTTP, parseia XML WebDAV,
    trata erros — não se o requests funciona.

Dependência adicional:
    pip install responses

Cobertura:
    ✓ PROPFIND — listagem bem-sucedida
    ✓ PROPFIND — parsing XML com tamanho e href
    ✓ PROPFIND — competência não encontrada (404)
    ✓ PROPFIND — resposta inesperada (500)
    ✓ PROPFIND — falha de conexão
    ✓ PROPFIND — XML malformado
    ✓ PROPFIND — filtra diretório raiz da listagem
    ✓ GET download — caminho feliz
    ✓ GET download — resume com Range header
    ✓ GET download — servidor sem suporte a Range (200 para Range)
    ✓ GET download — erro 4xx
    ✓ GET download — erro 5xx
    ✓ chunks() — iteração correta
    ✓ Context manager — fecha sessão
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import responses as responses_lib
from responses import RequestsMock

from rfb.client import RFBClient, ArquivoInfo
from rfb.errors import (
    CompetenciaNotFoundError,
    DownloadError,
    ListingError,
    ResumeNotSupportedError,
)


# ==================== CONSTANTES ====================

TOKEN = "YggdBLfdninEJX9"
COMPETENCIA = "2026-03"
BASE_URL = "https://arquivos.receitafederal.gov.br"
PROPFIND_URL = f"{BASE_URL}/public.php/dav/files/{TOKEN}/{COMPETENCIA}/"
DOWNLOAD_URL = f"{BASE_URL}/public.php/dav/files/{TOKEN}/{COMPETENCIA}/Empresas0.zip"


# ==================== XML HELPERS ====================

def xml_propfind(arquivos: list[dict]) -> str:
    """
    Gera XML de resposta WebDAV PROPFIND para testes.

    Simula a estrutura real retornada pelo Nextcloud da RFB.
    Cada dict em arquivos deve ter: href, nome, tamanho (opcional).

    Args:
        arquivos: lista de dicts com metadados dos arquivos

    Returns:
        String XML no formato WebDAV multistatus
    """
    responses_xml = ""
    for arq in arquivos:
        tamanho = arq.get("tamanho", 0)
        responses_xml += f"""
        <d:response>
            <d:href>{arq['href']}</d:href>
            <d:propstat>
                <d:prop>
                    <d:getcontentlength>{tamanho}</d:getcontentlength>
                    <d:resourcetype/>
                </d:prop>
                <d:status>HTTP/1.1 200 OK</d:status>
            </d:propstat>
        </d:response>
        """

    return f"""<?xml version="1.0" encoding="utf-8"?>
    <d:multistatus xmlns:d="DAV:">
        <d:response>
            <d:href>/public.php/dav/files/{TOKEN}/{COMPETENCIA}/</d:href>
            <d:propstat>
                <d:prop>
                    <d:resourcetype><d:collection/></d:resourcetype>
                </d:prop>
                <d:status>HTTP/1.1 200 OK</d:status>
            </d:propstat>
        </d:response>
        {responses_xml}
    </d:multistatus>"""


# ==================== FIXTURE ====================

@pytest.fixture
def client() -> RFBClient:
    """RFBClient com token de teste."""
    return RFBClient(token=TOKEN)


# ==================== LISTAGEM — CAMINHO FELIZ ====================

class TestListarArquivos:
    """Testes de listagem via WebDAV PROPFIND."""

    @responses_lib.activate
    def test_retorna_lista_de_arquivo_info(self, client: RFBClient):
        """
        PROPFIND bem-sucedido deve retornar lista de ArquivoInfo
        com nome, tamanho e href de cada arquivo.
        """
        responses_lib.add(
            responses_lib.Response(
                method="PROPFIND",
                url=PROPFIND_URL,
                body=xml_propfind([
                    {
                        "href": f"/public.php/dav/files/{TOKEN}/{COMPETENCIA}/Empresas0.zip",
                        "tamanho": 486_000_000
                    },
                    {
                        "href": f"/public.php/dav/files/{TOKEN}/{COMPETENCIA}/Municipios.zip",
                        "tamanho": 43_443
                    },
                ]),
                status=207,
                content_type="application/xml"
            )
        )

        arquivos = client.listar_arquivos(COMPETENCIA)

        assert len(arquivos) == 2
        assert all(isinstance(a, ArquivoInfo) for a in arquivos)

    @responses_lib.activate
    def test_arquivo_info_tem_nome_correto(self, client: RFBClient):
        """Nome do ArquivoInfo deve ser extraído corretamente do href."""
        responses_lib.add(
            responses_lib.Response(
                method="PROPFIND",
                url=PROPFIND_URL,
                body=xml_propfind([{
                    "href": f"/public.php/dav/files/{TOKEN}/{COMPETENCIA}/Empresas0.zip",
                    "tamanho": 486_000_000
                }]),
                status=207,
                content_type="application/xml"
            )
        )

        arquivos = client.listar_arquivos(COMPETENCIA)

        assert arquivos[0].nome == "Empresas0.zip"

    @responses_lib.activate
    def test_arquivo_info_tem_tamanho_correto(self, client: RFBClient):
        """Tamanho em bytes deve vir do campo getcontentlength do WebDAV."""
        responses_lib.add(
            responses_lib.Response(
                method="PROPFIND",
                url=PROPFIND_URL,
                body=xml_propfind([{
                    "href": f"/public.php/dav/files/{TOKEN}/{COMPETENCIA}/Empresas0.zip",
                    "tamanho": 486_000_000
                }]),
                status=207,
                content_type="application/xml"
            )
        )

        arquivos = client.listar_arquivos(COMPETENCIA)

        assert arquivos[0].tamanho_bytes == 486_000_000

    @responses_lib.activate
    def test_filtra_diretorio_raiz(self, client: RFBClient):
        """
        O próprio diretório da competência aparece como primeiro
        elemento na resposta PROPFIND — deve ser filtrado.
        O XML helper já inclui o diretório raiz — verificamos
        que ele não aparece na lista retornada.
        """
        responses_lib.add(
            responses_lib.Response(
                method="PROPFIND",
                url=PROPFIND_URL,
                body=xml_propfind([{
                    "href": f"/public.php/dav/files/{TOKEN}/{COMPETENCIA}/Empresas0.zip",
                    "tamanho": 100
                }]),
                status=207,
                content_type="application/xml"
            )
        )

        arquivos = client.listar_arquivos(COMPETENCIA)

        # apenas Empresas0.zip — diretório raiz filtrado
        nomes = [a.nome for a in arquivos]
        assert COMPETENCIA not in nomes
        assert "Empresas0.zip" in nomes

    @responses_lib.activate
    def test_lista_vazia_retorna_lista_vazia(self, client: RFBClient):
        """Diretório vazio deve retornar lista vazia sem erro."""
        responses_lib.add(
            responses_lib.Response(
                method="PROPFIND",
                url=PROPFIND_URL,
                body=xml_propfind([]),
                status=207,
                content_type="application/xml"
            )
        )

        arquivos = client.listar_arquivos(COMPETENCIA)

        assert arquivos == []

    @responses_lib.activate
    def test_tamanho_zero_quando_ausente(self, client: RFBClient):
        """
        Se getcontentlength não está presente no XML,
        tamanho_bytes deve ser 0 — não deve lançar erro.
        """
        xml_sem_tamanho = f"""<?xml version="1.0"?>
        <d:multistatus xmlns:d="DAV:">
            <d:response>
                <d:href>/public.php/dav/files/{TOKEN}/{COMPETENCIA}/Empresas0.zip</d:href>
                <d:propstat>
                    <d:prop/>
                    <d:status>HTTP/1.1 200 OK</d:status>
                </d:propstat>
            </d:response>
        </d:multistatus>"""

        responses_lib.add(
            responses_lib.Response(
                method="PROPFIND",
                url=PROPFIND_URL,
                body=xml_sem_tamanho,
                status=207,
                content_type="application/xml"
            )
        )

        arquivos = client.listar_arquivos(COMPETENCIA)

        assert arquivos[0].tamanho_bytes == 0


# ==================== LISTAGEM — ERROS ====================

class TestListarArquivosErros:
    """Falhas na listagem WebDAV."""

    @responses_lib.activate
    def test_404_lanca_competencia_not_found(self, client: RFBClient):
        """
        HTTP 404 indica que a pasta do mês não foi publicada.
        Deve lançar CompetenciaNotFoundError — não ListingError genérico.
        Permite que o pipeline sugira a competência anterior.
        """
        responses_lib.add(
            responses_lib.Response(
                method="PROPFIND",
                url=PROPFIND_URL,
                status=404
            )
        )

        with pytest.raises(CompetenciaNotFoundError) as exc_info:
            client.listar_arquivos(COMPETENCIA)

        assert COMPETENCIA in str(exc_info.value)

    @responses_lib.activate
    def test_500_lanca_listing_error(self, client: RFBClient):
        """Erro 5xx do servidor deve lançar ListingError."""
        responses_lib.add(
            responses_lib.Response(
                method="PROPFIND",
                url=PROPFIND_URL,
                status=500
            )
        )

        with pytest.raises(ListingError):
            client.listar_arquivos(COMPETENCIA)

    @responses_lib.activate
    def test_xml_malformado_lanca_listing_error(self, client: RFBClient):
        """XML inválido na resposta deve lançar ListingError."""
        responses_lib.add(
            responses_lib.Response(
                method="PROPFIND",
                url=PROPFIND_URL,
                body="<xml malformado sem fechamento",
                status=207,
                content_type="application/xml"
            )
        )

        with pytest.raises(ListingError, match="XML"):
            client.listar_arquivos(COMPETENCIA)

    def test_falha_conexao_lanca_listing_error(self, client: RFBClient):
        """
        Falha de conexão TCP deve lançar ListingError.
        Usa patch direto pois responses não simula ConnectionError.
        """
        from requests.exceptions import ConnectionError as RequestsConnectionError

        with patch.object(
            client._session,
            "request",
            side_effect=RequestsConnectionError("falha TCP")
        ):
            with pytest.raises(ListingError, match="conexão"):
                client.listar_arquivos(COMPETENCIA)

    def test_timeout_lanca_listing_error(self, client: RFBClient):
        """Timeout na listagem deve lançar ListingError."""
        from requests.exceptions import Timeout

        with patch.object(
            client._session,
            "request",
            side_effect=Timeout("timeout")
        ):
            with pytest.raises(ListingError, match="Timeout"):
                client.listar_arquivos(COMPETENCIA)

    @responses_lib.activate
    def test_competencia_not_found_e_subclasse_de_listing_error(
        self, client: RFBClient
    ):
        """
        CompetenciaNotFoundError deve ser capturável como ListingError.
        Garante hierarquia de herança correta.
        """
        responses_lib.add(
            responses_lib.Response(
                method="PROPFIND",
                url=PROPFIND_URL,
                status=404
            )
        )

        with pytest.raises(ListingError):
            client.listar_arquivos(COMPETENCIA)


# ==================== DOWNLOAD ====================

class TestStreamDownload:
    """Testes de download via HTTP GET."""

    @responses_lib.activate
    def test_retorna_response_status_200(self, client: RFBClient):
        """Download bem-sucedido deve retornar Response com status 200."""
        responses_lib.add(
            responses_lib.Response(
                method="GET",
                url=DOWNLOAD_URL,
                body=b"conteudo_zip",
                status=200
            )
        )

        with client.stream_download(COMPETENCIA, "Empresas0.zip") as r:
            assert r.status_code == 200

    @responses_lib.activate
    def test_resume_envia_range_header(self, client: RFBClient):
        """
        Com byte_inicial > 0, request deve incluir header Range.
        Verifica que o header é montado corretamente no formato RFC 7233.
        """
        responses_lib.add(
            responses_lib.Response(
                method="GET",
                url=DOWNLOAD_URL,
                body=b"continuacao",
                status=206
            )
        )

        with client.stream_download(
            COMPETENCIA, "Empresas0.zip", byte_inicial=1024
        ) as r:
            assert r.status_code == 206

        # verifica que Range header foi enviado
        request_enviado = responses_lib.calls[0].request
        assert "Range" in request_enviado.headers
        assert request_enviado.headers["Range"] == "bytes=1024-"

    @responses_lib.activate
    def test_sem_range_header_sem_byte_inicial(self, client: RFBClient):
        """
        Com byte_inicial=0, request não deve incluir Range header.
        Garante que downloads novos não enviam Range desnecessário.
        """
        responses_lib.add(
            responses_lib.Response(
                method="GET",
                url=DOWNLOAD_URL,
                body=b"arquivo_completo",
                status=200
            )
        )

        with client.stream_download(COMPETENCIA, "Empresas0.zip", byte_inicial=0):
            pass

        request_enviado = responses_lib.calls[0].request
        assert "Range" not in request_enviado.headers

    @responses_lib.activate
    def test_200_para_range_lanca_resume_not_supported(
        self, client: RFBClient
    ):
        """
        Servidor que retorna 200 para request com Range não suporta resume.
        Deve lançar ResumeNotSupportedError para que o Downloader
        reinicie o download do zero.
        """
        responses_lib.add(
            responses_lib.Response(
                method="GET",
                url=DOWNLOAD_URL,
                body=b"arquivo_completo",
                status=200  # deveria ser 206 para Range request
            )
        )

        with pytest.raises(ResumeNotSupportedError):
            client.stream_download(
                COMPETENCIA, "Empresas0.zip", byte_inicial=512
            )

    @responses_lib.activate
    def test_416_retorna_response(self, client: RFBClient):
        """
        HTTP 416 significa arquivo já completamente baixado.
        Deve retornar Response sem lançar exceção —
        o Downloader trata esse status como sucesso.
        """
        responses_lib.add(
            responses_lib.Response(
                method="GET",
                url=DOWNLOAD_URL,
                status=416
            )
        )

        with client.stream_download(COMPETENCIA, "Empresas0.zip") as r:
            assert r.status_code == 416

    @responses_lib.activate
    def test_404_lanca_download_error(self, client: RFBClient):
        """HTTP 404 — arquivo não encontrado — deve lançar DownloadError."""
        responses_lib.add(
            responses_lib.Response(
                method="GET",
                url=DOWNLOAD_URL,
                status=404
            )
        )

        with pytest.raises(DownloadError) as exc_info:
            client.stream_download(COMPETENCIA, "Empresas0.zip")

        assert exc_info.value.status_code == 404

    @responses_lib.activate
    def test_500_lanca_download_error(self, client: RFBClient):
        """HTTP 500 — erro no servidor — deve lançar DownloadError."""
        responses_lib.add(
            responses_lib.Response(
                method="GET",
                url=DOWNLOAD_URL,
                status=500
            )
        )

        with pytest.raises(DownloadError) as exc_info:
            client.stream_download(COMPETENCIA, "Empresas0.zip")

        assert exc_info.value.status_code == 500

    def test_falha_conexao_lanca_download_error(self, client: RFBClient):
        """Falha TCP durante download deve lançar DownloadError."""
        from requests.exceptions import ConnectionError as RequestsConnectionError

        with patch.object(
            client._session,
            "get",
            side_effect=RequestsConnectionError("falha")
        ):
            with pytest.raises(DownloadError, match="conexão"):
                client.stream_download(COMPETENCIA, "Empresas0.zip")


# ==================== CHUNKS ====================

class TestChunks:
    """Iteração de chunks da Response."""

    def test_itera_chunks_nao_vazios(self, client: RFBClient):
        """chunks() deve yieldar apenas bytes não-vazios."""
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [
            b"chunk1",
            b"",        # chunk vazio — deve ser filtrado
            b"chunk2",
            b"chunk3",
        ]

        resultado = list(client.chunks(mock_response, chunk_size=1_000))

        assert resultado == [b"chunk1", b"chunk2", b"chunk3"]

    def test_chunks_vazios_sao_filtrados(self, client: RFBClient):
        """Chunks vazios não devem aparecer no resultado."""
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [b"", b"", b"dados"]

        resultado = list(client.chunks(mock_response, chunk_size=1_000))

        assert len(resultado) == 1
        assert resultado[0] == b"dados"

    def test_chunk_size_passado_ao_iter_content(self, client: RFBClient):
        """chunk_size deve ser repassado ao iter_content do requests."""
        mock_response = MagicMock()
        mock_response.iter_content.return_value = []

        list(client.chunks(mock_response, chunk_size=8_000_000))

        mock_response.iter_content.assert_called_once_with(
            chunk_size=8_000_000
        )


# ==================== CONTEXT MANAGER ====================

class TestContextManager:
    """RFBClient como context manager."""

    def test_fecha_sessao_ao_sair(self):
        """
        __exit__ deve chamar fechar() que fecha a sessão HTTP.
        Garante que conexões do pool são liberadas após o uso.
        """
        client = RFBClient(token=TOKEN)

        with patch.object(client, "fechar") as mock_fechar:
            with client:
                pass

        mock_fechar.assert_called_once()

    def test_fecha_sessao_mesmo_com_excecao(self):
        """
        Sessão deve ser fechada mesmo se exceção ocorrer dentro do with.
        Garante que conexões não vazam em caso de erro.
        """
        client = RFBClient(token=TOKEN)

        with patch.object(client, "fechar") as mock_fechar:
            with pytest.raises(ValueError):
                with client:
                    raise ValueError("erro simulado")

        mock_fechar.assert_called_once()


# ==================== ARQUIVO INFO ====================

class TestArquivoInfo:
    """Testes do dataclass ArquivoInfo."""

    def test_imutavel(self):
        """
        ArquivoInfo é frozen=True — atribuição deve lançar FrozenInstanceError.
        Imutabilidade garante que metadados do servidor não são alterados
        acidentalmente durante o processamento.
        """
        from dataclasses import FrozenInstanceError

        info = ArquivoInfo(
            nome="Empresas0.zip",
            tamanho_bytes=486_000_000,
            href="/dav/files/token/2026-03/Empresas0.zip"
        )

        with pytest.raises(FrozenInstanceError):
            info.nome = "outro.zip"  # type: ignore

    def test_igualdade_por_valor(self):
        """Dois ArquivoInfo com mesmos valores devem ser iguais."""
        a = ArquivoInfo("Empresas0.zip", 100, "/href")
        b = ArquivoInfo("Empresas0.zip", 100, "/href")
        assert a == b

    def test_desigualdade(self):
        """ArquivoInfo com valores diferentes não devem ser iguais."""
        a = ArquivoInfo("Empresas0.zip", 100, "/href")
        b = ArquivoInfo("Empresas1.zip", 100, "/href")
        assert a != b