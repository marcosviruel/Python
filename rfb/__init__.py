"""
rfb/__init__.py
---------------
Pacote de download e processamento de dados públicos da Receita Federal.

Expõe os componentes principais para uso externo:
    from rfb import Config, Pipeline, RFBClient
"""

from rfb.config import Config
from rfb.client import RFBClient, ArquivoInfo
from rfb.pipeline import Pipeline, SumarioPipeline
from rfb.errors import RFBError

__version__ = "1.0.0"
__all__ = [
    "Config",
    "RFBClient",
    "ArquivoInfo",
    "Pipeline",
    "SumarioPipeline",
    "RFBError",
]