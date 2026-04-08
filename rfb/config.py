"""
config.py
---------
Configuração centralizada do pipeline RFB.

Responsabilidades:
    - Carregar configuração de variáveis de ambiente (.env)
    - Permitir override via argumentos CLI
    - Validar configuração antes de iniciar o pipeline
    - Expor configuração tipada para todos os módulos

Por que variáveis de ambiente?
-------------------------------
Hardcodar configuração no código é uma má prática porque:
    - Tokens e paths vazam em repositórios git
    - Mudar configuração exige alterar código (viola Open/Closed Principle)
    - Impossibilita rodar o mesmo código em ambientes diferentes
      (local, CI, produção) sem modificação

O padrão .env é amplamente adotado na indústria (12-factor app):
    https://12factor.net/config

Estrutura do .env esperado:
    RFB_TOKEN=YggdBLfdninEJX9
    RFB_COMPETENCIA=2026-03          # opcional — padrão: mês atual
    RFB_PASTA_DOWNLOAD=/data/zips    # opcional — padrão: ~/Downloads/RFB_ZIPS
    RFB_PASTA_EXTRAIDOS=/data/csv    # opcional — padrão: ~/Downloads/RFB_CSV
    RFB_MAX_WORKERS=3                # opcional — padrão: 3
    RFB_CHUNK_SIZE=8000000           # opcional — padrão: 8MB
    RFB_TIMEOUT_TOTAL=3600           # opcional — padrão: 1h
    RFB_TIMEOUT_SEM_PROGRESSO=300    # opcional — padrão: 5min
    RFB_TAMANHO_MINIMO_ZIP=10000     # opcional — padrão: 10KB
    RFB_ESPACO_MINIMO_GB=25          # opcional — padrão: 25GB
"""

import argparse
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# python-dotenv é opcional — se não estiver instalado, apenas ignora o .env
# instalar com: pip install python-dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()  # carrega .env do diretório atual, se existir
    _DOTENV_DISPONIVEL = True
except ImportError:
    _DOTENV_DISPONIVEL = False


def _competencia_padrao() -> str:
    """
    Retorna a competência do mês atual no formato YYYY-MM.

    Calculado uma única vez na inicialização da Config para evitar
    inconsistências em execuções que cruzam a virada do mês.
    """
    return datetime.now().strftime("%Y-%m")


def _pasta_padrao_download() -> Path:
    return Path.home() / "Downloads" / "RFB_ZIPS"


def _pasta_padrao_extraidos() -> Path:
    return Path.home() / "Downloads" / "RFB_CSV"


@dataclass
class Config:
    """
    Configuração tipada e validada do pipeline RFB.

    Todos os campos têm valores padrão sensatos para uso local.
    Em produção, os campos sensíveis (token) devem vir de variáveis
    de ambiente — nunca hardcodados no código.

    Exemplo de uso:
        # carrega do ambiente (.env ou variáveis do sistema)
        cfg = Config.from_env()

        # carrega do ambiente + override via CLI
        cfg = Config.from_cli()

        # instância direta para testes
        cfg = Config(token="test_token", max_workers=1)
    """

    # --- credenciais ---
    # token do share público da Receita Federal no Nextcloud
    token: str = ""

    # --- escopo ---
    # competência no formato YYYY-MM (ex: "2026-03")
    competencia: str = field(default_factory=_competencia_padrao)

    # prefixos dos arquivos a baixar — filtra os 21 arquivos relevantes
    # dentre os ~37 disponíveis na pasta
    prefixos: tuple = ("Estabelecimentos", "Empresas", "Municipios")

    # --- paths ---
    pasta_download: Path = field(default_factory=_pasta_padrao_download)
    pasta_extraidos: Path = field(default_factory=_pasta_padrao_extraidos)

    # --- performance ---
    # número de downloads simultâneos
    # 3 é o ponto ótimo empiricamente determinado para conexões domésticas
    # com o servidor da RFB — acima de 3 o ganho é marginal (<10s)
    max_workers: int = 3

    # tamanho do chunk de leitura em bytes
    # 8MB reduz syscalls de I/O vs chunks menores sem pressionar RAM
    # com 16GB de RAM disponível, 3 workers × 8MB = 24MB de buffer máximo
    chunk_size: int = 8_000_000

    # --- timeouts ---
    # tempo máximo total por arquivo em segundos (1h)
    timeout_total: int = 3600

    # tempo máximo sem receber dados antes de abortar (5min)
    # evita travamentos silenciosos em conexões instáveis
    timeout_sem_progresso: int = 300

    # --- validação ---
    # tamanho mínimo em bytes para considerar ZIP válido (10KB)
    # Municipios.zip tem ~42KB — threshold conservador para detectar
    # respostas de erro do servidor salvas como arquivo
    tamanho_minimo_zip: int = 10_000

    # espaço livre mínimo em GB necessário antes de iniciar
    # estimativa: ~25GB para Empresas + Estabelecimentos + Municipios extraídos
    espaco_minimo_gb: float = 25.0

    def __post_init__(self):
        """
        Converte tipos e cria diretórios após inicialização.

        Chamado automaticamente pelo dataclass após __init__.
        Garante que paths são sempre objetos Path (não strings)
        mesmo quando carregados de variáveis de ambiente.
        """
        # garante que paths são sempre Path, mesmo vindos de strings
        self.pasta_download = Path(self.pasta_download)
        self.pasta_extraidos = Path(self.pasta_extraidos)

        # cria diretórios se não existirem
        self.pasta_download.mkdir(parents=True, exist_ok=True)
        self.pasta_extraidos.mkdir(parents=True, exist_ok=True)

    def validar(self) -> None:
        """
        Valida a configuração antes de iniciar o pipeline.

        Levanta ValueError com mensagem clara se algum campo
        obrigatório estiver ausente ou inválido.

        Chamado explicitamente pelo pipeline antes de qualquer operação,
        evitando falhas tardias no meio de um download de horas.
        """
        erros = []

        if not self.token:
            erros.append(
                "Token não configurado. "
                "Defina RFB_TOKEN no .env ou passe --token via CLI."
            )

        # valida formato YYYY-MM
        try:
            datetime.strptime(self.competencia, "%Y-%m")
        except ValueError:
            erros.append(
                f"Competência inválida: '{self.competencia}'. "
                f"Formato esperado: YYYY-MM (ex: 2026-03)"
            )

        if self.max_workers < 1:
            erros.append(f"max_workers deve ser >= 1, recebido: {self.max_workers}")

        if self.chunk_size < 1_000:
            erros.append(f"chunk_size deve ser >= 1000 bytes, recebido: {self.chunk_size}")

        if self.espaco_minimo_gb <= 0:
            erros.append(f"espaco_minimo_gb deve ser > 0, recebido: {self.espaco_minimo_gb}")

        if not self.prefixos:
            erros.append("Nenhum prefixo configurado — nada a baixar.")

        if erros:
            raise ValueError(
                "Configuração inválida:\n" +
                "\n".join(f"  - {e}" for e in erros)
            )

    @classmethod
    def from_env(cls) -> "Config":
        """
        Cria Config a partir de variáveis de ambiente.

        Variáveis não definidas usam os valores padrão do dataclass.
        Isso permite que o script funcione localmente sem .env,
        exigindo apenas RFB_TOKEN em produção.

        Returns:
            Config: instância validada pronta para uso
        """
        cfg = cls(
            token=os.getenv("RFB_TOKEN", ""),
            competencia=os.getenv("RFB_COMPETENCIA", _competencia_padrao()),
            pasta_download=Path(os.getenv("RFB_PASTA_DOWNLOAD", str(_pasta_padrao_download()))),
            pasta_extraidos=Path(os.getenv("RFB_PASTA_EXTRAIDOS", str(_pasta_padrao_extraidos()))),
            max_workers=int(os.getenv("RFB_MAX_WORKERS", "3")),
            chunk_size=int(os.getenv("RFB_CHUNK_SIZE", "8000000")),
            timeout_total=int(os.getenv("RFB_TIMEOUT_TOTAL", "3600")),
            timeout_sem_progresso=int(os.getenv("RFB_TIMEOUT_SEM_PROGRESSO", "300")),
            tamanho_minimo_zip=int(os.getenv("RFB_TAMANHO_MINIMO_ZIP", "10000")),
            espaco_minimo_gb=float(os.getenv("RFB_ESPACO_MINIMO_GB", "25.0")),
        )
        cfg.validar()
        return cfg

    @classmethod
    def from_cli(cls) -> "Config":
        """
        Cria Config combinando variáveis de ambiente com argumentos CLI.

        Precedência: CLI > variável de ambiente > valor padrão

        Útil para:
            - Rodar para uma competência específica sem editar .env
            - Testar com configuração diferente sem alterar arquivos
            - Integração com scripts de automação (cron, CI)

        Exemplo:
            python main.py --competencia 2026-02 --max-workers 2
        """
        # carrega base do ambiente primeiro
        base = cls.from_env()

        parser = argparse.ArgumentParser(
            description="Pipeline de download de dados públicos da Receita Federal",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter
        )

        parser.add_argument(
            "--token",
            default=base.token,
            help="Token do share público da RFB no Nextcloud"
        )
        parser.add_argument(
            "--competencia",
            default=base.competencia,
            help="Competência no formato YYYY-MM (ex: 2026-03)"
        )
        parser.add_argument(
            "--pasta-download",
            default=str(base.pasta_download),
            help="Diretório para salvar os ZIPs baixados"
        )
        parser.add_argument(
            "--pasta-extraidos",
            default=str(base.pasta_extraidos),
            help="Diretório para os CSVs extraídos"
        )
        parser.add_argument(
            "--max-workers",
            type=int,
            default=base.max_workers,
            help="Número de downloads simultâneos"
        )
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=base.chunk_size,
            help="Tamanho do chunk de download em bytes"
        )

        args = parser.parse_args()

        cfg = cls(
            token=args.token,
            competencia=args.competencia,
            pasta_download=Path(args.pasta_download),
            pasta_extraidos=Path(args.pasta_extraidos),
            max_workers=args.max_workers,
            chunk_size=args.chunk_size,
            # mantém os demais do ambiente
            timeout_total=base.timeout_total,
            timeout_sem_progresso=base.timeout_sem_progresso,
            tamanho_minimo_zip=base.tamanho_minimo_zip,
            espaco_minimo_gb=base.espaco_minimo_gb,
        )
        cfg.validar()
        return cfg

    def competencia_anterior(self) -> str:
        """
        Retorna a competência do mês anterior no formato YYYY-MM.

        Usado pelo pipeline para sugerir alternativa quando a
        competência atual ainda não foi publicada pela RFB.

        Exemplos:
            "2026-03" → "2026-02"
            "2026-01" → "2025-12"  # virada de ano tratada corretamente
        """
        ano, mes = map(int, self.competencia.split("-"))
        if mes == 1:
            return f"{ano - 1}-12"
        return f"{ano}-{mes - 1:02d}"

    def __repr__(self) -> str:
        """
        Representação segura — nunca expõe o token completo.

        Importante para logs e debugging sem vazar credenciais.
        """
        token_seguro = f"{self.token[:4]}****" if self.token else "não configurado"
        return (
            f"Config("
            f"token={token_seguro}, "
            f"competencia={self.competencia}, "
            f"prefixos={self.prefixos}, "
            f"max_workers={self.max_workers}, "
            f"chunk_size={self.chunk_size // 1_000_000}MB"
            f")"
        )