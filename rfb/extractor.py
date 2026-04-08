"""
extractor.py
------------
Extração e renomeação de arquivos ZIP do pipeline RFB.

Responsabilidade única:
    Receber um arquivo ZIP validado, extrair seu conteúdo para o
    diretório de destino e renomear o arquivo extraído para um nome
    legível baseado no ZIP de origem.

Por que renomear?
-----------------
A Receita Federal distribui arquivos com nomes internos no formato
de mainframe (ex: K3241.K03200Y0.D60314.EMPRECSV) — sem extensão
reconhecível e sem relação óbvia com o conteúdo.

A renomeação mapeia esses nomes para nomes semânticos:
    K3241.K03200Y0.D60314.EMPRECSV  →  Empresas0.csv
    K3241.K03200Y0.D60314.ESTABELE  →  Estabelecimentos0.csv
    F.K03200$Z.D60314.MUNICCSV      →  Municipios.csv

Estratégia de renomeação:
    O nome correto vem do ZIP de origem (ex: Empresas0.zip → Empresas0.csv).
    O arquivo interno é identificado por correspondência de stem com a
    lista de arquivos internos retornada pelo Validator.

    Essa abordagem é determinística — não depende de heurística de
    conteúdo nem de padrões de nome do mainframe que podem mudar.

Idempotência:
    Arquivos já extraídos são detectados pelo arquivo marcador .done
    criado ao final de cada extração bem-sucedida.
    Re-executar o pipeline é seguro — arquivos concluídos são pulados.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from .errors import ExtractionError, RenameError


class Extractor:
    """
    Extrai e renomeia arquivos ZIP do pipeline RFB.

    Recebe a lista de arquivos internos do Validator (evitando
    reabrir o ZIP) e orquestra extração + renomeação em sequência.

    Arquivo marcador (.done):
        Criado em pasta_extraidos após extração e renomeação bem-sucedidas.
        Permite que o pipeline detecte arquivos já processados e os pule
        em re-execuções sem re-validar ou re-extrair.

    Exemplo de uso:
        extractor = Extractor(
            pasta_extraidos=cfg.pasta_extraidos
        )

        # arquivos_internos vem do Validator.validar()
        extractor.extrair(
            nome="Empresas0.zip",
            caminho=Path("/downloads/Empresas0.zip"),
            arquivos_internos=["K3241.K03200Y0.D60314.EMPRECSV"]
        )
    """

    def __init__(self, pasta_extraidos: Path):
        """
        Args:
            pasta_extraidos: diretório de destino para os CSVs extraídos
        """
        self._pasta = pasta_extraidos

    def extrair(
        self,
        nome: str,
        caminho: Path,
        arquivos_internos: list[str]
    ) -> Path:
        """
        Extrai ZIP e renomeia o arquivo resultante.

        A extração e renomeação são operações separadas internamente,
        mas expostas como uma única operação atômica para o pipeline —
        ou ambas completam, ou o arquivo .done não é criado e o
        pipeline pode re-tentar na próxima execução.

        Args:
            nome: nome lógico do ZIP (ex: "Empresas0.zip")
                  usado para derivar o nome final do CSV
            caminho: path físico do ZIP no disco
            arquivos_internos: lista de nomes de arquivos dentro do ZIP
                               retornada pelo Validator — evita reabrir o ZIP

        Returns:
            Path do arquivo CSV renomeado (ex: /csv/Empresas0.csv)

        Raises:
            ExtractionError: falha durante extração do ZIP
            RenameError: extração ok mas renomeação falhou
        """
        nome_base = Path(nome).stem  # "Empresas0.zip" → "Empresas0"
        destino_csv = self._pasta / f"{nome_base}.csv"
        done_file = self._pasta / f".{nome_base}.done"

        # idempotência — arquivo já processado em execução anterior
        if done_file.exists():
            return destino_csv

        # extração
        self._extrair_zip(nome=nome, caminho=caminho)

        # renomeação — antes de criar .done para garantir atomicidade
        # se renomeação falhar, .done não é criado e pipeline re-tenta
        self._renomear(
            nome=nome,
            arquivos_internos=arquivos_internos,
            destino=destino_csv
        )

        # marca como concluído apenas após tudo bem-sucedido
        done_file.touch()

        return destino_csv

    def ja_extraido(self, nome: str) -> bool:
        """
        Verifica se o arquivo já foi extraído e renomeado.

        Baseado na existência do arquivo .done — mais confiável que
        verificar apenas o CSV, pois o .done só é criado após
        extração E renomeação bem-sucedidas.

        Args:
            nome: nome do ZIP (ex: "Empresas0.zip")

        Returns:
            True se o arquivo foi completamente processado
        """
        nome_base = Path(nome).stem
        done_file = self._pasta / f".{nome_base}.done"
        return done_file.exists()

    def limpar_done_files(self) -> int:
        """
        Remove todos os arquivos .done do diretório de extração.

        Chamado ao final do pipeline para limpar marcadores temporários.
        Retorna o número de arquivos removidos para logging.

        Returns:
            Número de arquivos .done removidos
        """
        removidos = 0
        for done in self._pasta.glob(".*.done"):
            done.unlink()
            removidos += 1
        return removidos

    def _extrair_zip(self, nome: str, caminho: Path) -> None:
        """
        Extrai o conteúdo do ZIP para o diretório de destino.

        Args:
            nome: nome lógico para mensagens de erro
            caminho: path físico do ZIP

        Raises:
            ExtractionError: qualquer falha durante a extração
        """
        try:
            with zipfile.ZipFile(caminho, "r") as zip_ref:
                zip_ref.extractall(self._pasta)

        except zipfile.BadZipFile as e:
            # ZIP passou na validação mas falhou na extração —
            # raro, mas possível se o arquivo foi modificado entre
            # validação e extração (ex: disco com bad sectors)
            raise ExtractionError(
                f"ZIP corrompido durante extração (passou na validação): {e}",
                arquivo=nome
            )

        except OSError as e:
            # erros de I/O — disco cheio, permissão negada, etc.
            raise ExtractionError(
                f"Erro de I/O durante extração: {e}",
                arquivo=nome
            )

    def _renomear(
        self,
        nome: str,
        arquivos_internos: list[str],
        destino: Path
    ) -> None:
        """
        Renomeia arquivo extraído para nome semântico baseado no ZIP.

        Estratégia de correspondência:
            Para cada arquivo interno do ZIP, busca no diretório de
            extração um arquivo cujo stem (nome sem extensão) corresponda
            ao stem do arquivo interno.

            Correspondência por stem exato é determinística — evita
            matches parciais que poderiam renomear o arquivo errado
            quando múltiplos arquivos têm prefixo similar.

        Exemplo:
            ZIP: Empresas0.zip
            Interno: K3241.K03200Y0.D60314.EMPRECSV
            Stem interno: K3241.K03200Y0.D60314
            Candidato no disco: K3241.K03200Y0.D60314.csv (já renomeado
                                pelo script anterior) ou
                                K3241.K03200Y0.D60314.EMPRECSV (recém extraído)
            Destino: Empresas0.csv

        Args:
            nome: nome do ZIP para mensagens de erro
            arquivos_internos: lista de arquivos internos do ZIP
            destino: path final do CSV renomeado

        Raises:
            RenameError: nenhum arquivo interno encontrado no disco
        """
        if destino.exists():
            # já renomeado em execução anterior — idempotente
            return

        # constrói índice por stem — O(1) por lookup
        # evita varredura O(n) do diretório para cada arquivo interno
        candidatos: dict[str, Path] = {
            f.stem: f
            for f in self._pasta.iterdir()
            if f.is_file()
            and not f.name.startswith(".")
            and f.suffix != ".csv"
        }

        for interno in arquivos_internos:
            interno_stem = Path(interno).stem
            candidato = candidatos.get(interno_stem)

            if candidato and candidato.exists():
                try:
                    candidato.rename(destino)
                    return
                except OSError as e:
                    raise RenameError(
                        arquivo=nome,
                        destino=str(destino),
                        motivo=str(e)
                    )

        # nenhum arquivo interno encontrado no disco
        # pode indicar extração parcial ou nome inesperado
        raise RenameError(
            arquivo=nome,
            destino=str(destino),
            motivo=(
                f"Nenhum dos arquivos internos foi encontrado no disco: "
                f"{arquivos_internos}"
            )
        )