"""
validator.py
------------
Validação de arquivos ZIP antes da extração.

Responsabilidade única:
    Garantir que um arquivo ZIP baixado está íntegro e pronto
    para extração — detectando corrupção antes de desperdiçar
    tempo e I/O de disco numa extração fadada a falhar.

Por que validar antes de extrair?
-----------------------------------
Sem validação, um ZIP corrompido só falha na extração — após
potencialmente horas de download. A validação antecipada permite:
    - Falha rápida com mensagem clara
    - Preservação do arquivo corrompido para inspeção
    - Re-download imediato sem reprocessar arquivos válidos

Níveis de validação (do mais rápido ao mais lento):
    1. Existência do arquivo       — stat() — microssegundos
    2. Tamanho mínimo              — stat() — microssegundos
    3. Estrutura ZIP válida        — lê diretório central — milissegundos
    4. Integridade de conteúdo     — testzip() lê todos os bytes — segundos

O nível 4 (testzip) é o único que detecta corrupção real de dados.
Os níveis 1-3 detectam apenas problemas estruturais óbvios.
"""

from __future__ import annotations

from pathlib import Path

import zipfile

from .errors import (
    CorruptedZipError,
    EmptyZipError,
    FileTooSmallError,
    ValidationError,
)


class Validator:
    """
    Validador de arquivos ZIP do pipeline RFB.

    Executa validação em múltiplos níveis — do mais barato ao mais
    custoso — interrompendo assim que detecta um problema.

    Projetado para ser mockável nos testes — recebe o path do arquivo
    como argumento em vez de depender de estado global.

    Exemplo de uso:
        validator = Validator(tamanho_minimo=10_000)

        try:
            internos = validator.validar("Empresas0.zip", Path("/downloads/Empresas0.zip"))
        except ValidationError as e:
            logger.error(f"Arquivo inválido: {e}")
    """

    def __init__(self, tamanho_minimo: int = 10_000):
        """
        Args:
            tamanho_minimo: tamanho mínimo em bytes para considerar
                            o arquivo válido. Padrão de 10KB detecta
                            respostas de erro do servidor (páginas HTML)
                            salvas como arquivo acidentalmente.
        """
        self._tamanho_minimo = tamanho_minimo

    def validar(self, nome: str, caminho: Path) -> list[str]:
        """
        Executa validação completa de um arquivo ZIP.

        Executa os 4 níveis de validação em sequência.
        Interrompe e lança exceção no primeiro problema encontrado.

        Args:
            nome: nome lógico do arquivo (para mensagens de erro)
            caminho: path físico do arquivo no disco

        Returns:
            Lista de nomes de arquivos internos do ZIP —
            reutilizada pelo Extractor para renomeação,
            evitando reabrir o ZIP desnecessariamente.

        Raises:
            FileTooSmallError: arquivo menor que tamanho_minimo
            EmptyZipError: ZIP válido mas sem arquivos internos
            CorruptedZipError: CRC inválido em algum arquivo interno
            ValidationError: arquivo não existe ou não é um ZIP válido
        """
        # nível 1 — existência
        self._verificar_existencia(nome, caminho)

        # nível 2 — tamanho mínimo
        self._verificar_tamanho(nome, caminho)

        # nível 3 e 4 — estrutura e integridade
        # ambos abrem o ZIP uma única vez para evitar I/O duplo
        return self._verificar_integridade(nome, caminho)

    def _verificar_existencia(self, nome: str, caminho: Path) -> None:
        """
        Verifica se o arquivo existe no caminho informado.

        Raises:
            ValidationError: arquivo não encontrado
        """
        if not caminho.exists():
            raise ValidationError(
                f"Arquivo não encontrado: {caminho}",
                arquivo=nome
            )

        # garante que é um arquivo, não um diretório
        if not caminho.is_file():
            raise ValidationError(
                f"Path não é um arquivo: {caminho}",
                arquivo=nome
            )

    def _verificar_tamanho(self, nome: str, caminho: Path) -> None:
        """
        Verifica se o arquivo tem tamanho mínimo esperado.

        Um arquivo muito pequeno geralmente indica:
            - Download interrompido logo no início
            - Resposta de erro do servidor (página HTML de 404/403)
              salva como arquivo pelo código de download

        Raises:
            FileTooSmallError: tamanho abaixo do mínimo configurado
        """
        tamanho = caminho.stat().st_size

        if tamanho < self._tamanho_minimo:
            raise FileTooSmallError(
                arquivo=nome,
                tamanho_real=tamanho,
                tamanho_minimo=self._tamanho_minimo
            )

    def _verificar_integridade(self, nome: str, caminho: Path) -> list[str]:
        """
        Verifica estrutura e integridade do conteúdo do ZIP.

        Executa dois níveis em uma única abertura do arquivo:
            - Nível 3: verifica se é um ZIP válido (lê diretório central)
            - Nível 4: verifica CRC de cada arquivo interno (testzip)

        testzip() lê todos os bytes do ZIP e valida o CRC de cada
        arquivo interno — é o único método que detecta corrupção
        real de dados, não apenas problemas estruturais.

        Returns:
            Lista de nomes dos arquivos internos do ZIP

        Raises:
            ValidationError: arquivo não é um ZIP válido
            EmptyZipError: ZIP válido mas sem arquivos internos
            CorruptedZipError: CRC inválido detectado pelo testzip
        """
        try:
            with zipfile.ZipFile(caminho, "r") as z:
                # nível 3 — lista arquivos internos
                # lança BadZipFile se a estrutura do ZIP for inválida
                internos = z.namelist()

                if not internos:
                    raise EmptyZipError(
                        f"ZIP não contém arquivos internos",
                        arquivo=nome
                    )

                # nível 4 — verifica CRC de cada arquivo interno
                # retorna None se todos os CRCs são válidos
                # retorna o nome do primeiro arquivo corrompido se houver problema
                arquivo_corrompido = z.testzip()

                if arquivo_corrompido is not None:
                    raise CorruptedZipError(
                        arquivo=nome,
                        arquivo_interno_corrompido=arquivo_corrompido
                    )

                return internos

        except (EmptyZipError, CorruptedZipError):
            # relança erros customizados sem encapsular
            raise

        except zipfile.BadZipFile as e:
            raise ValidationError(
                f"Estrutura ZIP inválida: {e}",
                arquivo=nome
            )

        except OSError as e:
            # erro de I/O ao ler o arquivo — disco com problema,
            # permissão negada, etc.
            raise ValidationError(
                f"Erro de I/O ao ler arquivo: {e}",
                arquivo=nome
            )

    def verificar_espaco_disco(
        self,
        caminho: Path,
        espaco_minimo_gb: float
    ) -> None:
        """
        Verifica se há espaço livre suficiente no disco.

        Chamado pelo pipeline antes de iniciar downloads e extrações
        para evitar operações parciais por falta de espaço.

        Usa estimativa conservadora baseada no tamanho total esperado
        dos arquivos extraídos (~25GB para o conjunto completo da RFB).

        Args:
            caminho: diretório usado para medir espaço disponível
            espaco_minimo_gb: espaço mínimo necessário em GB

        Raises:
            InsufficientDiskSpaceError: espaço livre abaixo do mínimo
        """
        import shutil
        from .errors import InsufficientDiskSpaceError

        _, _, livre = shutil.disk_usage(caminho)
        livre_gb = livre / (1024 ** 3)
        necessario_bytes = espaco_minimo_gb * (1024 ** 3)

        if livre < necessario_bytes:
            raise InsufficientDiskSpaceError(
                livre_gb=livre_gb,
                necessario_gb=espaco_minimo_gb
            )