"""
tests/test_config.py
--------------------
Testes unitários do Config.

Cobertura:
    ✓ Instância direta com valores padrão
    ✓ Validação — token ausente
    ✓ Validação — competência inválida
    ✓ Validação — max_workers inválido
    ✓ Validação — prefixos vazios
    ✓ from_env() — carrega variáveis de ambiente
    ✓ from_env() — valores padrão quando variável ausente
    ✓ from_env() — falha sem token
    ✓ competencia_anterior() — mês normal
    ✓ competencia_anterior() — virada de ano
    ✓ __repr__ — não expõe token completo
    ✓ __post_init__ — cria diretórios automaticamente
    ✓ __post_init__ — converte strings para Path
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfb.config import Config


# ==================== INSTÂNCIA DIRETA ====================

class TestConfigInstancia:
    """Testes de instância direta e valores padrão."""

    def test_instancia_com_token(self, tmp_path: Path):
        """Config com token deve ser criada sem erro."""
        cfg = Config(
            token="token_teste",
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )
        assert cfg.token == "token_teste"

    def test_competencia_padrao_formato_correto(self, tmp_path: Path):
        """
        Competência padrão deve estar no formato YYYY-MM.
        Não testamos o valor exato — depende da data atual.
        """
        cfg = Config(
            token="x",
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )
        partes = cfg.competencia.split("-")
        assert len(partes) == 2
        assert len(partes[0]) == 4  # ano com 4 dígitos
        assert len(partes[1]) == 2  # mês com 2 dígitos

    def test_prefixos_padrao(self, tmp_path: Path):
        """Prefixos padrão devem cobrir os três tipos de arquivo da RFB."""
        cfg = Config(
            token="x",
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )
        assert "Empresas" in cfg.prefixos
        assert "Estabelecimentos" in cfg.prefixos
        assert "Municipios" in cfg.prefixos

    def test_max_workers_padrao(self, tmp_path: Path):
        """
        max_workers padrão deve ser 3 — valor empiricamente determinado
        como ponto ótimo para conexões domésticas com o servidor da RFB.
        """
        cfg = Config(
            token="x",
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )
        assert cfg.max_workers == 3


# ==================== POST INIT ====================

class TestPostInit:
    """Testes de __post_init__ — criação de diretórios e conversão de tipos."""

    def test_cria_pasta_download(self, tmp_path: Path):
        """pasta_download deve ser criada se não existir."""
        pasta = tmp_path / "nova_pasta" / "zips"
        assert not pasta.exists()

        Config(
            token="x",
            pasta_download=pasta,
            pasta_extraidos=tmp_path / "csv",
        )

        assert pasta.exists()

    def test_cria_pasta_extraidos(self, tmp_path: Path):
        """pasta_extraidos deve ser criada se não existir."""
        pasta = tmp_path / "nova_pasta" / "csv"
        assert not pasta.exists()

        Config(
            token="x",
            pasta_download=tmp_path / "zips",
            pasta_extraidos=pasta,
        )

        assert pasta.exists()

    def test_converte_string_para_path(self, tmp_path: Path):
        """
        Paths passados como string devem ser convertidos para Path.
        Necessário quando valores vêm de variáveis de ambiente (sempre strings).
        """
        cfg = Config(
            token="x",
            pasta_download=str(tmp_path / "zips"),   # string
            pasta_extraidos=str(tmp_path / "csv"),   # string
        )

        assert isinstance(cfg.pasta_download, Path)
        assert isinstance(cfg.pasta_extraidos, Path)

    def test_aceita_pasta_ja_existente(self, tmp_path: Path):
        """exist_ok=True — não deve falhar se pasta já existe."""
        pasta = tmp_path / "existente"
        pasta.mkdir()

        # não deve lançar FileExistsError
        Config(
            token="x",
            pasta_download=pasta,
            pasta_extraidos=tmp_path / "csv",
        )


# ==================== VALIDAÇÃO ====================

class TestValidar:
    """Testes de validação de configuração."""

    def test_token_vazio_lanca_value_error(self, tmp_path: Path):
        """
        Token vazio deve lançar ValueError com mensagem clara.
        Token é o único campo obrigatório sem valor padrão.
        """
        cfg = Config(
            token="",
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )

        with pytest.raises(ValueError, match="Token"):
            cfg.validar()

    def test_competencia_invalida_lanca_value_error(self, tmp_path: Path):
        """Competência fora do formato YYYY-MM deve ser rejeitada."""
        cfg = Config(
            token="x",
            competencia="03-2026",  # formato invertido
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )

        with pytest.raises(ValueError, match="Competência"):
            cfg.validar()

    def test_competencia_texto_invalido(self, tmp_path: Path):
        """Texto aleatório como competência deve ser rejeitado."""
        cfg = Config(
            token="x",
            competencia="março-2026",
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )

        with pytest.raises(ValueError, match="Competência"):
            cfg.validar()

    def test_max_workers_zero_lanca_value_error(self, tmp_path: Path):
        """max_workers=0 deve ser rejeitado — pipeline não executaria nada."""
        cfg = Config(
            token="x",
            max_workers=0,
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )

        with pytest.raises(ValueError, match="max_workers"):
            cfg.validar()

    def test_max_workers_negativo_lanca_value_error(self, tmp_path: Path):
        """max_workers negativo deve ser rejeitado."""
        cfg = Config(
            token="x",
            max_workers=-1,
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )

        with pytest.raises(ValueError, match="max_workers"):
            cfg.validar()

    def test_prefixos_vazios_lanca_value_error(self, tmp_path: Path):
        """Sem prefixos, pipeline não baixaria nenhum arquivo."""
        cfg = Config(
            token="x",
            prefixos=(),
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )

        with pytest.raises(ValueError, match="prefixo"):
            cfg.validar()

    def test_chunk_size_muito_pequeno_lanca_value_error(self, tmp_path: Path):
        """chunk_size abaixo de 1000 bytes é inválido."""
        cfg = Config(
            token="x",
            chunk_size=500,
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )

        with pytest.raises(ValueError, match="chunk_size"):
            cfg.validar()

    def test_configuracao_valida_nao_lanca_excecao(self, tmp_path: Path):
        """Configuração completa e válida não deve lançar nenhuma exceção."""
        cfg = Config(
            token="token_valido",
            competencia="2026-03",
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )

        try:
            cfg.validar()
        except ValueError as e:
            pytest.fail(f"Não deveria lançar ValueError: {e}")

    def test_multiplos_erros_listados_juntos(self, tmp_path: Path):
        """
        Quando há múltiplos erros, todos devem aparecer na mensagem.
        Evita que o usuário precise corrigir um erro por vez.
        """
        cfg = Config(
            token="",           # erro 1
            max_workers=0,      # erro 2
            prefixos=(),        # erro 3
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )

        with pytest.raises(ValueError) as exc_info:
            cfg.validar()

        mensagem = str(exc_info.value)
        # todos os erros devem estar na mensagem
        assert "Token" in mensagem
        assert "max_workers" in mensagem
        assert "prefixo" in mensagem


# ==================== FROM_ENV ====================

class TestFromEnv:
    """Testes de carregamento via variáveis de ambiente."""

    def test_carrega_token_do_ambiente(
        self, monkeypatch, tmp_path: Path
    ):
        """RFB_TOKEN do ambiente deve ser usado como token."""
        monkeypatch.setenv("RFB_TOKEN", "token_do_env")
        monkeypatch.setenv("RFB_PASTA_DOWNLOAD", str(tmp_path / "zips"))
        monkeypatch.setenv("RFB_PASTA_EXTRAIDOS", str(tmp_path / "csv"))

        cfg = Config.from_env()

        assert cfg.token == "token_do_env"

    def test_carrega_competencia_do_ambiente(
        self, monkeypatch, tmp_path: Path
    ):
        """RFB_COMPETENCIA do ambiente deve sobrescrever o padrão."""
        monkeypatch.setenv("RFB_TOKEN", "x")
        monkeypatch.setenv("RFB_COMPETENCIA", "2026-01")
        monkeypatch.setenv("RFB_PASTA_DOWNLOAD", str(tmp_path / "zips"))
        monkeypatch.setenv("RFB_PASTA_EXTRAIDOS", str(tmp_path / "csv"))

        cfg = Config.from_env()

        assert cfg.competencia == "2026-01"

    def test_carrega_max_workers_do_ambiente(
        self, monkeypatch, tmp_path: Path
    ):
        """RFB_MAX_WORKERS do ambiente deve sobrescrever o padrão."""
        monkeypatch.setenv("RFB_TOKEN", "x")
        monkeypatch.setenv("RFB_MAX_WORKERS", "2")
        monkeypatch.setenv("RFB_PASTA_DOWNLOAD", str(tmp_path / "zips"))
        monkeypatch.setenv("RFB_PASTA_EXTRAIDOS", str(tmp_path / "csv"))

        cfg = Config.from_env()

        assert cfg.max_workers == 2

    def test_usa_valor_padrao_quando_variavel_ausente(
        self, monkeypatch, tmp_path: Path
    ):
        """
        Variáveis não definidas devem usar valores padrão do dataclass.
        Permite que o script funcione localmente sem .env completo.
        """
        monkeypatch.setenv("RFB_TOKEN", "x")
        monkeypatch.setenv("RFB_PASTA_DOWNLOAD", str(tmp_path / "zips"))
        monkeypatch.setenv("RFB_PASTA_EXTRAIDOS", str(tmp_path / "csv"))
        # RFB_MAX_WORKERS não definido — deve usar padrão (3)
        monkeypatch.delenv("RFB_MAX_WORKERS", raising=False)

        cfg = Config.from_env()

        assert cfg.max_workers == 3

    def test_from_env_sem_token_lanca_value_error(
        self, monkeypatch, tmp_path: Path
    ):
        """
        from_env() chama validar() internamente.
        Sem token, deve lançar ValueError antes de retornar.
        """
        monkeypatch.delenv("RFB_TOKEN", raising=False)
        monkeypatch.setenv("RFB_PASTA_DOWNLOAD", str(tmp_path / "zips"))
        monkeypatch.setenv("RFB_PASTA_EXTRAIDOS", str(tmp_path / "csv"))

        with pytest.raises(ValueError, match="Token"):
            Config.from_env()

    def test_from_env_retorna_config_validada(
        self, monkeypatch, tmp_path: Path
    ):
        """from_env() deve retornar instância de Config."""
        monkeypatch.setenv("RFB_TOKEN", "token_valido")
        monkeypatch.setenv("RFB_PASTA_DOWNLOAD", str(tmp_path / "zips"))
        monkeypatch.setenv("RFB_PASTA_EXTRAIDOS", str(tmp_path / "csv"))

        cfg = Config.from_env()

        assert isinstance(cfg, Config)


# ==================== COMPETENCIA_ANTERIOR ====================

class TestCompetenciaAnterior:
    """Testes de cálculo da competência anterior."""

    @pytest.mark.parametrize("competencia,esperado", [
        ("2026-03", "2026-02"),
        ("2026-06", "2026-05"),
        ("2026-12", "2026-11"),
        ("2026-02", "2026-01"),
    ])
    def test_mes_normal(
        self,
        tmp_path: Path,
        competencia: str,
        esperado: str
    ):
        """Mês normal — apenas decrementa o mês."""
        cfg = Config(
            token="x",
            competencia=competencia,
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )
        assert cfg.competencia_anterior() == esperado

    def test_virada_de_ano(self, tmp_path: Path):
        """
        Janeiro deve retornar dezembro do ano anterior.
        Caso especial que exige tratamento explícito.
        """
        cfg = Config(
            token="x",
            competencia="2026-01",
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )
        assert cfg.competencia_anterior() == "2025-12"

    def test_formato_com_zero_a_esquerda(self, tmp_path: Path):
        """
        Meses com um dígito devem ter zero à esquerda.
        "2026-03" → "2026-02", não "2026-2".
        """
        cfg = Config(
            token="x",
            competencia="2026-03",
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )
        anterior = cfg.competencia_anterior()
        mes = anterior.split("-")[1]
        assert len(mes) == 2


# ==================== REPR ====================

class TestRepr:
    """Testes de representação segura do Config."""

    def test_repr_nao_expoe_token_completo(self, tmp_path: Path):
        """
        __repr__ não deve expor o token completo.
        Token vazado em log é um incidente de segurança.
        """
        cfg = Config(
            token="YggdBLfdninEJX9",
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )

        repr_str = repr(cfg)

        # token completo não deve aparecer
        assert "YggdBLfdninEJX9" not in repr_str

    def test_repr_mostra_primeiros_caracteres_do_token(
        self, tmp_path: Path
    ):
        """
        Primeiros caracteres do token devem aparecer para identificação.
        Suficiente para confirmar qual token está sendo usado sem expô-lo.
        """
        cfg = Config(
            token="YggdBLfdninEJX9",
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )

        repr_str = repr(cfg)

        # primeiros 4 chars devem aparecer
        assert "Yggd" in repr_str
        assert "****" in repr_str

    def test_repr_token_nao_configurado(self, tmp_path: Path):
        """Sem token, repr deve indicar 'não configurado'."""
        cfg = Config(
            token="",
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )

        repr_str = repr(cfg)

        assert "não configurado" in repr_str

    def test_repr_inclui_competencia(self, tmp_path: Path):
        """Competência deve aparecer no repr para contexto."""
        cfg = Config(
            token="x",
            competencia="2026-03",
            pasta_download=tmp_path / "zips",
            pasta_extraidos=tmp_path / "csv",
        )

        assert "2026-03" in repr(cfg)