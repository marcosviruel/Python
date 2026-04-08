"""
main.py
-------
Ponto de entrada do pipeline de dados da Receita Federal.

Responsabilidade única:
    Inicializar configuração, construir o pipeline e executar.
    Nenhuma lógica de negócio aqui — apenas orquestração de alto nível.

Por que main.py é tão simples?
--------------------------------
Separar o ponto de entrada da lógica permite:
    1. Testar o pipeline sem executar main()
    2. Importar componentes individualmente sem efeitos colaterais
    3. Trocar a fonte de configuração (env, CLI, arquivo) sem
       alterar nenhuma lógica do pipeline

Modos de execução:
    # usa configuração do .env
    python main.py

    # override de competência via CLI
    python main.py --competencia 2026-02

    # override de workers via CLI
    python main.py --max-workers 2

    # combinado
    python main.py --competencia 2026-02 --max-workers 1

Código de saída:
    0 — pipeline concluído (mesmo com falhas parciais — ver sumário)
    1 — erro crítico antes de iniciar (config inválida, sem espaço)
    2 — nenhum arquivo encontrado
"""

from __future__ import annotations

import logging
import sys

from rfb.client import RFBClient
from rfb.config import Config
from rfb.errors import (
    CompetenciaNotFoundError,
    InsufficientDiskSpaceError,
    ListingError,
    RFBError,
)
from rfb.pipeline import Pipeline


# ==================== LOGGING ====================

def configurar_logging() -> None:
    """
    Configura logging para stdout com formato legível.

    Formato escolhido para equilíbrio entre informação e legibilidade:
        HH:MM:SS [LEVEL] mensagem

    Em produção com agregador de logs (Datadog, CloudWatch),
    trocar para JSON handler — o pipeline em si não muda.
    """
    formato = "%(asctime)s [%(levelname)s] %(message)s"
    data_formato = "%H:%M:%S"

    logging.basicConfig(
        level=logging.INFO,
        format=formato,
        datefmt=data_formato,
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    # silencia logs verbose de bibliotecas externas
    # requests e urllib3 logam cada conexão TCP — ruído desnecessário
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


# ==================== MAIN ====================

def main() -> int:
    """
    Executa o pipeline completo de dados da RFB.

    Returns:
        Código de saída do processo:
            0 — sucesso (total ou parcial)
            1 — erro crítico de configuração ou infraestrutura
            2 — nenhum arquivo encontrado
    """
    configurar_logging()
    logger = logging.getLogger("rfb.main")

    # carrega e valida configuração
    # from_cli() lê .env primeiro, depois aplica overrides do CLI
    # validar() lança ValueError se configuração estiver incompleta
    try:
        cfg = Config.from_cli()
    except ValueError as e:
        logger.error(f"Configuração inválida:\n{e}")
        logger.error(
            "Crie um arquivo .env na raiz do projeto com RFB_TOKEN=seu_token"
        )
        return 1

    logger.info(f"Configuração carregada: {cfg}")

    # executa pipeline com client HTTP como context manager
    # garante fechamento da sessão mesmo em caso de erro
    try:
        with RFBClient(
            token=cfg.token,
            timeout_conexao=10,
            timeout_leitura=60
        ) as client:
            pipeline = Pipeline.from_config(cfg, client)
            sumario = pipeline.executar()

    except InsufficientDiskSpaceError as e:
        # espaço insuficiente — erro de infraestrutura, não do pipeline
        logger.error(f"Espaço em disco insuficiente: {e}")
        logger.error(
            f"Libere pelo menos {cfg.espaco_minimo_gb:.0f}GB antes de executar."
        )
        return 1

    except CompetenciaNotFoundError as e:
        # mês não publicado — erro esperado no primeiro dia do mês
        logger.error(str(e))
        logger.info(
            f"Dica: a RFB geralmente publica os dados até o dia 10 do mês. "
            f"Tente: python main.py --competencia {cfg.competencia_anterior()}"
        )
        return 2

    except ListingError as e:
        # falha de rede ao listar — pode ser temporária
        logger.error(f"Falha ao listar arquivos: {e}")
        logger.info("Verifique sua conexão e tente novamente.")
        return 1

    except RFBError as e:
        # erro inesperado do pipeline
        logger.error(f"Erro no pipeline: {e}")
        return 1

    except KeyboardInterrupt:
        # interrupção manual — não é erro, downloads parciais são retomáveis
        logger.info("")
        logger.info("Pipeline interrompido pelo usuário.")
        logger.info(
            "Downloads parciais foram preservados — "
            "execute novamente para retomar."
        )
        return 0

    # avalia resultado
    if sumario.total == 0:
        logger.warning("Nenhum arquivo encontrado para os prefixos configurados.")
        return 2

    if sumario.falhas > 0 and sumario.sucessos == 0:
        # todas as tentativas falharam
        logger.error("Todos os arquivos falharam — verifique o log acima.")
        return 1

    # sucesso total ou parcial — sumário já foi logado pelo pipeline
    return 0


# ==================== EXECUÇÃO ====================

if __name__ == "__main__":
    sys.exit(main())