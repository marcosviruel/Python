"""
errors.py
---------
Define a hierarquia de erros customizados do pipeline RFB.

Por que erros customizados?
---------------------------
Usar `except Exception` genérico é uma má prática porque:
- Engloba erros de disco, rede e lógica no mesmo bloco
- Impossibilita tratamento específico por tipo de falha
- Dificulta debugging — o log perde contexto semântico

Com erros customizados, cada camada do pipeline lança e captura
exatamente o tipo de erro que conhece, sem vazar detalhes internos
para camadas superiores.

Hierarquia:
    RFBError
    ├── ListingError       — falha ao listar arquivos via WebDAV
    ├── DownloadError      — falha no download de um arquivo
    │   └── ResumeNotSupportedError  — servidor não suporta Range
    ├── ValidationError    — arquivo baixado não passa na validação
    │   ├── FileTooSmallError        — tamanho abaixo do mínimo
    │   ├── EmptyZipError            — ZIP sem arquivos internos
    │   └── CorruptedZipError        — CRC inválido ou estrutura corrompida
    ├── ExtractionError    — falha durante extração do ZIP
    └── RenameError        — falha ao renomear arquivo extraído
"""


class RFBError(Exception):
    """
    Erro base do pipeline RFB.

    Todos os erros customizados herdam daqui, permitindo que a
    camada de orquestração capture qualquer falha do pipeline
    com um único `except RFBError` quando necessário.
    """
    def __init__(self, message: str, arquivo: str = ""):
        super().__init__(message)
        self.arquivo = arquivo  # nome do arquivo envolvido, para logging estruturado

    def __str__(self) -> str:
        if self.arquivo:
            return f"[{self.arquivo}] {super().__str__()}"
        return super().__str__()


# ==================== LISTAGEM ====================

class ListingError(RFBError):
    """
    Falha ao listar arquivos disponíveis via WebDAV.

    Exemplos: servidor fora, competência não publicada, HTTP inesperado.
    """


class CompetenciaNotFoundError(ListingError):
    """
    A competência solicitada não existe no servidor.

    Lançado quando o WebDAV retorna 404, indicando que a pasta
    do mês ainda não foi publicada pela Receita Federal.
    Sugestão de competência anterior é incluída na mensagem.
    """


# ==================== DOWNLOAD ====================

class DownloadError(RFBError):
    """
    Falha no download de um arquivo após todas as tentativas de retry.

    Inclui o status HTTP quando disponível para facilitar diagnóstico.
    """
    def __init__(self, message: str, arquivo: str = "", status_code: int = 0):
        super().__init__(message, arquivo)
        # status HTTP da última tentativa (0 se não houve resposta)
        self.status_code = status_code


class ResumeNotSupportedError(DownloadError):
    """
    Servidor retornou HTTP 200 ao receber header Range.

    Indica que o servidor não suporta download parcial.
    O downloader deve reiniciar o download do zero nesse caso.
    """


class DownloadTimeoutError(DownloadError):
    """
    Download excedeu o tempo máximo permitido sem progresso
    ou ultrapassou o timeout total configurado.
    """


# ==================== VALIDAÇÃO ====================

class ValidationError(RFBError):
    """
    Arquivo baixado não passou na validação pré-extração.

    Erros de validação indicam que o arquivo não deve ser extraído —
    ele deve ser renomeado para CORROMPIDO_ e preservado para inspeção.
    """


class FileTooSmallError(ValidationError):
    """
    Tamanho do arquivo está abaixo do mínimo configurado.

    Geralmente indica download incompleto ou resposta de erro
    do servidor salva como arquivo (ex: página HTML de 404).
    """
    def __init__(self, arquivo: str, tamanho_real: int, tamanho_minimo: int):
        mensagem = (
            f"Arquivo muito pequeno: {tamanho_real} bytes "
            f"(mínimo esperado: {tamanho_minimo} bytes)"
        )
        super().__init__(mensagem, arquivo)
        self.tamanho_real = tamanho_real
        self.tamanho_minimo = tamanho_minimo


class EmptyZipError(ValidationError):
    """ZIP válido estruturalmente mas sem arquivos internos."""


class CorruptedZipError(ValidationError):
    """
    ZIP com CRC inválido detectado por `testzip()`.

    O nome do arquivo interno corrompido é incluído para facilitar
    o diagnóstico — útil quando o ZIP contém múltiplos arquivos.
    """
    def __init__(self, arquivo: str, arquivo_interno_corrompido: str):
        mensagem = f"CRC inválido no arquivo interno: {arquivo_interno_corrompido}"
        super().__init__(mensagem, arquivo)
        self.arquivo_interno_corrompido = arquivo_interno_corrompido


# ==================== EXTRAÇÃO ====================

class ExtractionError(RFBError):
    """
    Falha durante a extração do ZIP para o diretório de destino.

    Pode indicar falta de espaço em disco, permissões insuficientes
    ou corrupção não detectada na validação.
    """


class InsufficientDiskSpaceError(ExtractionError):
    """
    Espaço livre em disco insuficiente para extração.

    Lançado antes de iniciar o download ou a extração,
    evitando operações parciais que corrompem o estado.
    """
    def __init__(self, livre_gb: float, necessario_gb: float):
        mensagem = (
            f"Espaço insuficiente: {livre_gb:.2f} GB livre, "
            f"~{necessario_gb:.1f} GB necessário"
        )
        super().__init__(mensagem)
        self.livre_gb = livre_gb
        self.necessario_gb = necessario_gb


# ==================== RENOMEAÇÃO ====================

class RenameError(RFBError):
    """
    Falha ao renomear arquivo extraído para nome legível.

    Não é crítico — o arquivo foi extraído com sucesso,
    apenas o nome final ficou incorreto. O pipeline deve
    logar e continuar sem abortar.
    """
    def __init__(self, arquivo: str, destino: str, motivo: str):
        mensagem = f"Não foi possível renomear para {destino}: {motivo}"
        super().__init__(mensagem, arquivo)
        self.destino = destino