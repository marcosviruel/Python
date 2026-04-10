"""
tests/conftest.py
-----------------
Fixtures compartilhadas entre todos os testes do pipeline RFB.

O que é conftest.py?
---------------------
Arquivo especial reconhecido automaticamente pelo pytest.
Fixtures definidas aqui ficam disponíveis para todos os arquivos
de teste no mesmo diretório e subdiretórios — sem necessidade de
importação explícita.

Por que centralizar fixtures?
------------------------------
1. Evita duplicação — fixtures comuns (Config, paths temporários,
   mocks de client) definidas uma vez, usadas em qualquer teste
2. Consistência — todos os testes usam os mesmos dados de base
3. Manutenção — mudar um fixture reflete em todos os testes

Fixtures disponíveis:
    cfg             — Config com valores de teste (paths temporários)
    tmp_download    — diretório temporário para ZIPs
    tmp_extraidos   — diretório temporário para CSVs
    zip_valido      — ZIP real com conteúdo mínimo válido
    zip_corrompido  — ZIP com CRC inválido para testes de validação
    zip_vazio       — ZIP válido estruturalmente mas sem arquivos
    mock_client     — mock de RFBClient para testes sem rede
    arquivo_info    — ArquivoInfo de exemplo
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rfb.config import Config
from rfb.client import ArquivoInfo


# ==================== FIXTURES DE CONFIGURAÇÃO ====================

@pytest.fixture
def tmp_download(tmp_path: Path) -> Path:
    """
    Diretório temporário para ZIPs baixados.

    tmp_path é uma fixture built-in do pytest que cria um diretório
    único por teste — automaticamente removido após cada teste.
    Isso garante isolamento total entre testes.
    """
    pasta = tmp_path / "RFB_ZIPS"
    pasta.mkdir()
    return pasta


@pytest.fixture
def tmp_extraidos(tmp_path: Path) -> Path:
    """
    Diretório temporário para CSVs extraídos.

    Separado de tmp_download para espelhar a estrutura real
    do pipeline — download e extração em pastas distintas.
    """
    pasta = tmp_path / "RFB_CSV"
    pasta.mkdir()
    return pasta


@pytest.fixture
def cfg(tmp_download: Path, tmp_extraidos: Path) -> Config:
    """
    Config com valores seguros para testes.

    Usa diretórios temporários em vez de ~/Downloads para garantir
    que testes não interferem com dados reais do usuário.

    Timeouts reduzidos para que testes falhem rapidamente
    em vez de esperar minutos por timeouts reais.

    Token com valor de teste — testes que precisam de rede real
    devem usar cfg_real ou mockar o client.
    """
    return Config(
        token="test_token_rfb",
        competencia="2026-03",
        prefixos=("Estabelecimentos", "Empresas", "Municipios"),
        pasta_download=tmp_download,
        pasta_extraidos=tmp_extraidos,
        max_workers=1,          # sequencial em testes — determinístico
        chunk_size=1_000,       # chunk pequeno para testar iteração
        timeout_total=10,       # falha rápida em testes
        timeout_sem_progresso=5,
        tamanho_minimo_zip=10,  # threshold baixo para ZIPs de teste
        espaco_minimo_gb=0.0,   # desativa verificação de disco em testes
    )


# ==================== FIXTURES DE ARQUIVOS ====================

@pytest.fixture
def zip_valido(tmp_download: Path) -> Path:
    """
    Cria um ZIP válido com conteúdo mínimo realista.

    Simula a estrutura real dos ZIPs da RFB:
        - Nome externo: Empresas0.zip
        - Nome interno: K3241.K03200Y0.D60314.EMPRECSV
        - Conteúdo: linhas CSV com separador ;

    O conteúdo CSV é mínimo mas válido — suficiente para testar
    extração e renomeação sem precisar de dados reais da RFB.

    Returns:
        Path do ZIP criado em tmp_download
    """
    caminho = tmp_download / "Empresas0.zip"

    # conteúdo CSV mínimo simulando formato RFB (separador ;)
    conteudo_csv = (
        "00000000000191;EMPRESA TESTE SA;2;3012401;"
        "2010-01-15;1000000;SP;01310100\n"
        "00000000000272;OUTRA EMPRESA LTDA;2;4711301;"
        "2015-06-20;500000;RJ;20040020\n"
    ).encode("latin1")

    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
        # nome interno no formato mainframe da RFB
        z.writestr("K3241.K03200Y0.D60314.EMPRECSV", conteudo_csv)

    return caminho


@pytest.fixture
def zip_municipios(tmp_download: Path) -> Path:
    """
    ZIP de Municípios simulando o arquivo real da RFB.

    Nome interno diferente dos Empresas — testa que a renomeação
    funciona corretamente para diferentes padrões de nome.
    """
    caminho = tmp_download / "Municipios.zip"

    conteudo = (
        "0001;ALTA FLORESTA D'OESTE;RO\n"
        "0002;ARIQUEMES;RO\n"
        "0003;CABIXI;RO\n"
    ).encode("latin1")

    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("F.K03200$Z.D60314.MUNICCSV", conteudo)

    return caminho


@pytest.fixture
def zip_corrompido(tmp_download: Path) -> Path:
    """
    Cria um ZIP com CRC inválido para testar detecção de corrupção.

    Estratégia:
        1. Cria ZIP válido em memória
        2. Modifica bytes do conteúdo (após o header ZIP)
        3. Salva o ZIP adulterado no disco

    O testzip() do Python detecta a inconsistência de CRC
    — exatamente o que o Validator deve capturar.
    """
    caminho = tmp_download / "Corrompido.zip"

    # cria ZIP válido em buffer de memória
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as z:
        z.writestr("arquivo.csv", "conteudo valido")

    # adultera bytes do conteúdo — corrompe o CRC
    dados = bytearray(buffer.getvalue())
    # modifica bytes no meio do arquivo (área de dados, não header ZIP)
    # offset 30 é tipicamente onde começa o conteúdo no ZIP STORED
    for i in range(30, min(45, len(dados))):
        dados[i] = (dados[i] + 1) % 256

    caminho.write_bytes(bytes(dados))
    return caminho


@pytest.fixture
def zip_vazio(tmp_download: Path) -> Path:
    """
    ZIP válido estruturalmente mas sem arquivos internos.

    Testa que o Validator rejeita ZIPs vazios mesmo quando
    a estrutura ZIP é tecnicamente válida.
    """
    caminho = tmp_download / "Vazio.zip"

    # cria ZIP sem adicionar nenhum arquivo
    with zipfile.ZipFile(caminho, "w") as _:
        pass

    return caminho


@pytest.fixture
def arquivo_pequeno(tmp_download: Path) -> Path:
    """
    Arquivo com poucos bytes — simula download incompleto.

    Testa que o Validator rejeita arquivos menores que tamanho_minimo.
    """
    caminho = tmp_download / "Pequeno.zip"
    caminho.write_bytes(b"PK\x03\x04")  # apenas magic bytes do ZIP
    return caminho


# ==================== FIXTURES DE MOCK ====================

@pytest.fixture
def arquivo_info() -> ArquivoInfo:
    """
    ArquivoInfo de exemplo para testes de listagem e pipeline.

    Representa Empresas0.zip com tamanho realista (~486MB).
    """
    return ArquivoInfo(
        nome="Empresas0.zip",
        tamanho_bytes=486_000_000,
        href="/public.php/dav/files/test_token/2026-03/Empresas0.zip"
    )


@pytest.fixture
def mock_client(zip_valido: Path) -> MagicMock:
    """
    Mock de RFBClient para testes sem dependência de rede.

    Simula:
        - listar_arquivos(): retorna lista com Empresas0.zip
        - stream_download(): retorna Response com conteúdo do zip_valido
        - chunks(): itera sobre bytes do ZIP real

    Usar MagicMock permite verificar se os métodos foram chamados
    com os argumentos corretos — útil para testar a orquestração
    do Pipeline sem executar operações reais.

    Exemplo em teste:
        def test_pipeline_chama_download(mock_client, cfg):
            pipeline = Pipeline.from_config(cfg, mock_client)
            pipeline.executar()
            mock_client.listar_arquivos.assert_called_once_with("2026-03")
    """
    client = MagicMock()

    # listar_arquivos retorna lista com um arquivo de teste
    client.listar_arquivos.return_value = [
        ArquivoInfo(
            nome="Empresas0.zip",
            tamanho_bytes=486_000_000,
            href="/dav/files/test_token/2026-03/Empresas0.zip"
        )
    ]

    # stream_download retorna mock de Response com status 200
    mock_response = MagicMock()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.status_code = 200

    client.stream_download.return_value = mock_response

    # chunks itera sobre o conteúdo real do ZIP de teste
    zip_bytes = zip_valido.read_bytes()
    # divide em chunks de 1KB para testar iteração
    chunk_size_teste = 1_000
    chunks = [
        zip_bytes[i:i + chunk_size_teste]
        for i in range(0, len(zip_bytes), chunk_size_teste)
    ]
    client.chunks.return_value = iter(chunks)

    return client


# ==================== HELPERS ====================

def criar_done_file(pasta: Path, nome_zip: str) -> Path:
    """
    Helper para criar arquivo .done em testes de idempotência.

    Usado em testes que verificam se o pipeline pula arquivos
    já processados sem re-baixar ou re-extrair.

    Args:
        pasta: diretório de extração
        nome_zip: nome do ZIP (ex: "Empresas0.zip")

    Returns:
        Path do arquivo .done criado

    Exemplo:
        def test_pipeline_pula_arquivo_processado(cfg, mock_client):
            criar_done_file(cfg.pasta_extraidos, "Empresas0.zip")
            pipeline = Pipeline.from_config(cfg, mock_client)
            pipeline.executar()
            mock_client.stream_download.assert_not_called()
    """
    nome_base = Path(nome_zip).stem
    done_file = pasta / f".{nome_base}.done"
    done_file.touch()
    return done_file