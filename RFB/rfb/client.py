"""
client.py
---------
Camada de comunicação HTTP/WebDAV com o servidor da Receita Federal.

Responsabilidade única:
    Abstrair toda comunicação de rede — listagem via WebDAV (PROPFIND)
    e download via HTTP GET — expondo uma interface limpa para os
    módulos superiores (downloader, pipeline).

Por que isolar a camada HTTP?
------------------------------
1. Testabilidade — módulos superiores podem ser testados com um
   client mockado, sem depender de rede real
2. Substituibilidade — se a RFB mudar de Nextcloud para outro servidor,
   apenas este arquivo muda
3. Responsabilidade clara — retry, timeout e headers HTTP ficam aqui,
   não espalhados pelo código

Protocolo WebDAV:
    A RFB usa Nextcloud, que expõe seus arquivos via WebDAV.
    PROPFIND é o método HTTP do protocolo WebDAV para listar
    recursos de um diretório — equivalente a um `ls` via HTTP.
    Referência: https://tools.ietf.org/html/rfc4918

Protocolo de download:
    Downloads usam HTTP GET padrão com suporte a Range requests
    (RFC 7233) para permitir resume de downloads interrompidos.
    Referência: https://tools.ietf.org/html/rfc7233
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Generator, Protocol

import requests
from requests import Response

from .errors import (
    CompetenciaNotFoundError,
    DownloadError,
    ListingError,
    ResumeNotSupportedError,
)


# ==================== PROTOCOL (INTERFACE) ====================

class HTTPClientProtocol(Protocol):
    """
    Interface formal para o cliente HTTP.

    Define o contrato que qualquer implementação de cliente HTTP
    deve seguir — seja o cliente real (RFBClient) ou um mock de teste.

    Por que Protocol em vez de ABC?
    Protocol (PEP 544) usa duck typing estrutural — qualquer classe
    que implemente os métodos corretos satisfaz a interface,
    sem precisar herdar explicitamente. É o padrão moderno em Python
    para interfaces mockáveis.
    """

    def listar_arquivos(self, competencia: str) -> list[str]:
        """Lista nomes de arquivos ZIP disponíveis para a competência."""
        ...

    def stream_download(
        self,
        competencia: str,
        nome: str,
        byte_inicial: int = 0
    ) -> Response:
        """
        Inicia um download em streaming.

        Args:
            competencia: mês no formato YYYY-MM
            nome: nome do arquivo ZIP (ex: "Empresas0.zip")
            byte_inicial: posição para resume (0 = download completo)

        Returns:
            Response com stream aberto — o caller é responsável por
            fechar a conexão (usar como context manager)
        """
        ...


# ==================== DATACLASS DE RESPOSTA ====================

@dataclass(frozen=True)
class ArquivoInfo:
    """
    Metadados de um arquivo disponível no servidor.

    Imutável (frozen=True) — representa um snapshot do estado
    do servidor no momento da listagem.

    Attributes:
        nome: nome do arquivo (ex: "Empresas0.zip")
        tamanho_bytes: tamanho reportado pelo servidor (0 se não disponível)
        href: path completo no WebDAV
    """
    nome: str
    tamanho_bytes: int
    href: str


# ==================== CLIENTE REAL ====================

class RFBClient:
    """
    Cliente HTTP para o servidor público da Receita Federal.

    Encapsula toda comunicação com o Nextcloud da RFB:
        - Listagem de arquivos via PROPFIND (WebDAV)
        - Download de arquivos via GET com suporte a Range

    Implementa HTTPClientProtocol — pode ser substituído por
    MockRFBClient nos testes sem alterar nenhum módulo superior.

    Exemplo de uso:
        client = RFBClient(token="YggdBLfdninEJX9")
        arquivos = client.listar_arquivos("2026-03")
        with client.stream_download("2026-03", "Empresas0.zip") as r:
            for chunk in r.iter_content(chunk_size=8_000_000):
                ...
    """

    # URL base do servidor da RFB — separada para facilitar mock em testes
    BASE_URL = "https://arquivos.receitafederal.gov.br"

    # namespace XML do protocolo WebDAV
    # definido pela RFC 4918 — nunca muda
    _DAV_NS = {"d": "DAV:"}

    def __init__(self, token: str, timeout_conexao: int = 10, timeout_leitura: int = 60):
        """
        Args:
            token: token do share público no Nextcloud da RFB
            timeout_conexao: segundos para estabelecer conexão TCP
            timeout_leitura: segundos para receber primeiro byte após conectar
        """
        self._token = token
        # tupla de timeout — padrão requests: (conexão, leitura)
        self._timeout = (timeout_conexao, timeout_leitura)

        # sessão reutilizada entre requests — evita overhead de
        # handshake TCP/TLS a cada download
        self._session = requests.Session()

    def listar_arquivos(self, competencia: str) -> list[ArquivoInfo]:
        """
        Lista arquivos disponíveis para uma competência via WebDAV PROPFIND.

        PROPFIND é o método HTTP do WebDAV para listar propriedades
        de recursos — equivalente a um directory listing.
        Depth: 1 significa "liste apenas o conteúdo direto desta pasta"
        (sem recursão em subpastas).

        Args:
            competencia: mês no formato YYYY-MM (ex: "2026-03")

        Returns:
            Lista de ArquivoInfo com metadados dos arquivos disponíveis

        Raises:
            CompetenciaNotFoundError: pasta do mês não existe no servidor
            ListingError: qualquer outro erro de comunicação
        """
        url = f"{self.BASE_URL}/public.php/dav/files/{self._token}/{competencia}/"

        try:
            response = self._session.request(
                method="PROPFIND",
                url=url,
                headers={"Depth": "1"},
                # autenticação anônima — Nextcloud exige o header mesmo
                # para shares públicos sem senha
                auth=("anonymous", ""),
                timeout=30
            )
        except requests.exceptions.ConnectionError as e:
            raise ListingError(f"Falha de conexão ao listar {competencia}: {e}")
        except requests.exceptions.Timeout:
            raise ListingError(f"Timeout ao listar arquivos de {competencia}")
        except requests.exceptions.RequestException as e:
            raise ListingError(f"Erro HTTP ao listar {competencia}: {e}")

        # 404 indica que a pasta do mês não foi publicada ainda
        if response.status_code == 404:
            raise CompetenciaNotFoundError(
                f"Competência {competencia} não encontrada no servidor. "
                f"A pasta pode ainda não ter sido publicada pela RFB."
            )

        # 207 Multi-Status é a resposta padrão do WebDAV para PROPFIND
        if response.status_code not in (207, 200):
            raise ListingError(
                f"Resposta inesperada do WebDAV: HTTP {response.status_code} "
                f"ao listar {competencia}"
            )

        return self._parsear_propfind(response.text, competencia)

    def stream_download(
        self,
        competencia: str,
        nome: str,
        byte_inicial: int = 0
    ) -> Response:
        """
        Inicia download em streaming com suporte a resume.

        Retorna a Response com stream aberto — deve ser usado como
        context manager para garantir que a conexão seja fechada:

            with client.stream_download("2026-03", "Empresas0.zip") as r:
                for chunk in r.iter_content(...):
                    ...

        Args:
            competencia: mês no formato YYYY-MM
            nome: nome do arquivo ZIP
            byte_inicial: byte a partir do qual retomar (0 = início)
                          Se > 0, envia header Range para resume

        Returns:
            Response com stream aberto

        Raises:
            ResumeNotSupportedError: servidor ignorou Range e retornou 200
            DownloadError: erro HTTP 4xx/5xx ou falha de conexão
        """
        url = f"{self.BASE_URL}/public.php/dav/files/{self._token}/{competencia}/{nome}"

        headers = {}
        if byte_inicial > 0:
            # Range header (RFC 7233): solicita bytes a partir de byte_inicial
            # ex: "bytes=102400-" significa "do byte 102400 até o fim"
            headers["Range"] = f"bytes={byte_inicial}-"

        try:
            response = self._session.get(
                url=url,
                headers=headers,
                stream=True,  # não carrega o corpo na memória — itera em chunks
                timeout=self._timeout
            )
        except requests.exceptions.ConnectionError as e:
            raise DownloadError(f"Falha de conexão: {e}", arquivo=nome)
        except requests.exceptions.Timeout:
            raise DownloadError(f"Timeout ao conectar", arquivo=nome)
        except requests.exceptions.RequestException as e:
            raise DownloadError(f"Erro HTTP: {e}", arquivo=nome)

        # servidor ignorou o Range e devolveu o arquivo completo
        # isso acontece com servidores que não implementam RFC 7233
        if byte_inicial > 0 and response.status_code == 200:
            raise ResumeNotSupportedError(
                f"Servidor retornou HTTP 200 para request com Range — "
                f"resume não suportado para {nome}",
                arquivo=nome
            )

        # arquivo já completamente baixado
        if response.status_code == 416:
            return response

        if 400 <= response.status_code < 500:
            raise DownloadError(
                f"HTTP {response.status_code} — arquivo não disponível",
                arquivo=nome,
                status_code=response.status_code
            )

        if response.status_code >= 500:
            raise DownloadError(
                f"HTTP {response.status_code} — erro no servidor",
                arquivo=nome,
                status_code=response.status_code
            )

        return response

    def chunks(
        self,
        response: Response,
        chunk_size: int
    ) -> Generator[bytes, None, None]:
        """
        Itera sobre chunks de uma Response em streaming.

        Centraliza a iteração de chunks aqui para que o Downloader
        não precise conhecer detalhes do requests.

        Args:
            response: Response com stream aberto
            chunk_size: tamanho de cada chunk em bytes

        Yields:
            chunks de bytes não-vazios
        """
        for chunk in response.iter_content(chunk_size=chunk_size):
            # iter_content pode retornar chunks vazios em keepalive —
            # filtramos aqui para simplificar o Downloader
            if chunk:
                yield chunk

    def _parsear_propfind(self, xml_texto: str, competencia: str) -> list[ArquivoInfo]:
        """
        Parseia resposta XML do WebDAV PROPFIND.

        O WebDAV retorna um XML com um elemento <response> por arquivo.
        Cada <response> contém o href (path) e propriedades como
        tamanho (getcontentlength).

        Exemplo de resposta WebDAV:
            <multistatus>
                <response>
                    <href>/dav/files/TOKEN/2026-03/Empresas0.zip</href>
                    <propstat>
                        <prop>
                            <getcontentlength>510000000</getcontentlength>
                        </prop>
                    </propstat>
                </response>
            </multistatus>

        Args:
            xml_texto: corpo da resposta PROPFIND
            competencia: usado para filtrar o próprio diretório da listagem

        Returns:
            Lista de ArquivoInfo — exclui o diretório raiz da listagem

        Raises:
            ListingError: XML malformado ou estrutura inesperada
        """
        try:
            root = ET.fromstring(xml_texto)
        except ET.ParseError as e:
            raise ListingError(f"XML inválido na resposta WebDAV: {e}")

        arquivos = []

        for resp in root.findall("d:response", self._DAV_NS):
            href_elem = resp.find("d:href", self._DAV_NS)
            if href_elem is None:
                continue

            href = href_elem.text or ""
            nome = href.rstrip("/").split("/")[-1]

            # exclui o próprio diretório da competência que aparece
            # como primeiro elemento na resposta PROPFIND
            if not nome or nome == competencia:
                continue

            # tenta extrair tamanho — nem todos os recursos têm essa propriedade
            tamanho = 0
            tamanho_elem = resp.find(
                "d:propstat/d:prop/d:getcontentlength",
                self._DAV_NS
            )
            if tamanho_elem is not None and tamanho_elem.text:
                try:
                    tamanho = int(tamanho_elem.text)
                except ValueError:
                    pass  # tamanho inválido — mantém 0

            arquivos.append(ArquivoInfo(
                nome=nome,
                tamanho_bytes=tamanho,
                href=href
            ))

        return arquivos

    def fechar(self) -> None:
        """
        Fecha a sessão HTTP liberando conexões do pool.

        Deve ser chamado ao final do pipeline ou usar RFBClient
        como context manager:

            with RFBClient(token=cfg.token) as client:
                ...
        """
        self._session.close()

    def __enter__(self) -> "RFBClient":
        return self

    def __exit__(self, *args) -> None:
        self.fechar()