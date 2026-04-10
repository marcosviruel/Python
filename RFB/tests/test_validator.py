from __future__ import annotations

from pathlib import Path
import shutil
import zipfile

import pytest

from rfb.errors import (
    CorruptedZipError,
    EmptyZipError,
    FileTooSmallError,
    InsufficientDiskSpaceError,
    ValidationError,
)
from rfb.validator import Validator


# ==================== FIXTURE ====================

@pytest.fixture
def validator(cfg) -> Validator:
    return Validator(tamanho_minimo=cfg.tamanho_minimo_zip)


# ==================== HELPERS ====================

class FakeZip:
    def __init__(self, files=None, corrupted=None):
        self._files = files or []
        self._corrupted = corrupted

    def __enter__(self): return self
    def __exit__(self, *args): pass

    def namelist(self):
        return self._files

    def testzip(self):
        return self._corrupted


def fake_zip_ok():
    return FakeZip(["ok.txt"])


def fake_zip_empty():
    return FakeZip([])


def fake_zip_multi():
    return FakeZip(["a.txt", "b.txt"])


# ==================== UNIT TESTS ====================

@pytest.mark.parametrize(
    "threshold,deve_falhar",
    [
        (100, False),
        (1000, True),
    ],
)
def test_threshold_isolado(monkeypatch, tmp_path: Path, threshold: int, deve_falhar: bool):
    arquivo = tmp_path / "arquivo.zip"
    arquivo.write_bytes(b"x" * 500)

    validator = Validator(tamanho_minimo=threshold)

    if deve_falhar:
        with pytest.raises(FileTooSmallError):
            validator.validar("arquivo.zip", arquivo)
    else:
        monkeypatch.setattr(zipfile, "ZipFile", lambda *a, **k: fake_zip_ok())
        resultado = validator.validar("arquivo.zip", arquivo)
        assert resultado == ["ok.txt"]


def test_file_too_small_error_contrato(validator: Validator, arquivo_pequeno: Path):
    with pytest.raises(FileTooSmallError) as exc:
        validator.validar("Pequeno.zip", arquivo_pequeno)

    assert exc.value.tamanho_real == arquivo_pequeno.stat().st_size


@pytest.mark.parametrize("nome", ["nao_existe.zip", "fantasma.zip"])
def test_arquivo_inexistente(validator: Validator, tmp_path: Path, nome: str):
    caminho = tmp_path / nome

    with pytest.raises(ValidationError, match=nome):
        validator.validar(nome, caminho)


def test_espaco_insuficiente(monkeypatch, validator: Validator, tmp_path: Path):
    monkeypatch.setattr(shutil, "disk_usage", lambda _: (100, 99, 1))

    with pytest.raises(InsufficientDiskSpaceError):
        validator.verificar_espaco_disco(tmp_path, 1)


def test_espaco_contrato(monkeypatch, validator: Validator, tmp_path: Path):
    monkeypatch.setattr(shutil, "disk_usage", lambda _: (100, 99, 1))

    with pytest.raises(InsufficientDiskSpaceError) as exc:
        validator.verificar_espaco_disco(tmp_path, 1)

    assert hasattr(exc.value, "livre_gb")
    assert hasattr(exc.value, "necessario_gb")


# ==================== INTEGRATION ====================

def test_zip_vazio(validator: Validator, zip_vazio: Path):
    with pytest.raises(EmptyZipError, match="arquivos internos"):
        validator.validar("Vazio.zip", zip_vazio)


def test_zip_corrompido(validator: Validator, zip_corrompido: Path):
    with pytest.raises(CorruptedZipError) as exc:
        validator.validar("Corrompido.zip", zip_corrompido)

    assert exc.value.arquivo_interno_corrompido


@pytest.mark.parametrize("conteudo", [
    b"<html>404</html>",
    bytes(range(256)) * 5,
])
def test_nao_zip(validator: Validator, tmp_path: Path, conteudo: bytes):
    arquivo = tmp_path / "falso.zip"
    arquivo.write_bytes(conteudo)

    with pytest.raises(ValidationError, match="ZIP"):
        validator.validar("falso.zip", arquivo)


# ==================== EDGE CASES ====================

# 1. múltiplos arquivos

def test_zip_multiplos_arquivos(monkeypatch, validator: Validator, tmp_path: Path):
    arquivo = tmp_path / "arquivo.zip"
    arquivo.write_bytes(b"x" * 100)

    monkeypatch.setattr(zipfile, "ZipFile", lambda *a, **k: fake_zip_multi())

    resultado = validator.validar("arquivo.zip", arquivo)
    assert resultado == ["a.txt", "b.txt"]


# 2. path é diretório

def test_path_diretorio_lanca_erro(validator: Validator, tmp_path: Path):
    with pytest.raises(ValidationError, match="não é um arquivo"):
        validator.validar("dir", tmp_path)


# 3. BadZipFile explícito

def test_bad_zipfile_lanca_validation_error(monkeypatch, validator: Validator, tmp_path: Path):
    arquivo = tmp_path / "arquivo.zip"
    arquivo.write_bytes(b"x" * 100)

    def fake_zip(*args, **kwargs):
        raise zipfile.BadZipFile("bad zip")

    monkeypatch.setattr(zipfile, "ZipFile", fake_zip)

    with pytest.raises(ValidationError, match="ZIP inválida"):
        validator.validar("arquivo.zip", arquivo)


# 4. zip vazio via mock

def test_zip_vazio_mock(monkeypatch, validator: Validator, tmp_path: Path):
    arquivo = tmp_path / "arquivo.zip"
    arquivo.write_bytes(b"x" * 100)

    monkeypatch.setattr(zipfile, "ZipFile", lambda *a, **k: fake_zip_empty())

    with pytest.raises(EmptyZipError):
        validator.validar("arquivo.zip", arquivo)


# 5. permissão negada

def test_arquivo_sem_permissao(monkeypatch, validator: Validator, tmp_path: Path):
    arquivo = tmp_path / "arquivo.zip"
    arquivo.write_bytes(b"x" * 100)

    def fake_zip(*args, **kwargs):
        raise PermissionError("Permission denied")

    monkeypatch.setattr(zipfile, "ZipFile", fake_zip)

    with pytest.raises(ValidationError, match="I/O"):
        validator.validar("arquivo.zip", arquivo)
