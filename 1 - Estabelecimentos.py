import pandas as pd
import os
import time
import csv

# ================= CONFIGURAÇÕES DE AMBIENTE =================
# Pasta principal onde todos os resultados serão centralizados
PASTA_RAIZ = r"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python\CSVs"

# Onde os arquivos brutos (Estabelecimentos0.csv, etc) estão guardados
PASTA_ORIGEM_BRUTOS = os.path.join(PASTA_RAIZ, "Estabelecimentos")

# Onde o arquivo LIMPO será salvo (na raiz da sua pasta de trabalho)
ARQUIVO_SAIDA = os.path.join(PASTA_RAIZ, "1_Estabelecimentos_Ativos_Brasil.csv")

# Configurações de Leitura
CHUNKSIZE = 500_000
ENCODING_ORIGEM = "latin1"
SEPARADOR_ORIGEM = ";"

# Mapeamento técnico: Colunas originais da RFB vs Nomes amigáveis
MAPA_COLUNAS = {
    0: "cnpj_basico", 1: "cnpj_ordem", 2: "cnpj_dv", 3: "matriz_filial", 
    4: "nome_fantasia", 5: "situacao_cadastral", 10: "data_inicio", 
    11: "cnae_principal", 13: "tipo_logradouro", 14: "logradouro", 
    15: "numero", 16: "complemento", 17: "bairro", 18: "cep", 
    19: "uf", 20: "municipio", 21: "ddd_1", 22: "telefone_1", 
    23: "ddd_2", 24: "telefone_2", 27: "email"
}

COLUNAS_PARA_LER = list(MAPA_COLUNAS.keys())
NOMES_COLUNAS = list(MAPA_COLUNAS.values())

# ================= FUNÇÕES DE APOIO =================

def limpar_arquivo_antigo(caminho):
    """Garante que o processo comece do zero, evitando mix de dados antigos."""
    if os.path.exists(caminho):
        os.remove(caminho)
        print(f"[*] Arquivo antigo removido: {os.path.basename(caminho)}")

# ================= EXECUÇÃO PRINCIPAL =================

inicio_total = time.time()
total_ativos = 0
primeira_escrita = True

# Cria a PASTA_RAIZ se por acaso ela não existir
if not os.path.exists(PASTA_RAIZ):
    os.makedirs(PASTA_RAIZ)

limpar_arquivo_antigo(ARQUIVO_SAIDA)

print(f"\n{'='*60}")
print("INICIANDO FILTRAGEM DE ESTABELECIMENTOS ATIVOS")
print(f"Destino: {ARQUIVO_SAIDA}")
print(f"{'='*60}\n")

# Loop pelos 10 arquivos padrão da Receita Federal
for i in range(10):
    arquivo_nome = f"Estabelecimentos{i}.csv"
    caminho_input = os.path.join(PASTA_ORIGEM_BRUTOS, arquivo_nome)

    if not os.path.exists(caminho_input):
        print(f"[!] Pulando: {arquivo_nome} (Não localizado na subpasta Estabelecimentos)")
        continue

    print(f"> Processando: {arquivo_nome}")

    leitor = pd.read_csv(
        caminho_input,
        sep=SEPARADOR_ORIGEM,
        header=None,
        names=NOMES_COLUNAS,
        usecols=COLUNAS_PARA_LER,
        dtype=str,
        encoding=ENCODING_ORIGEM,
        chunksize=CHUNKSIZE,
        engine="c",
        quoting=csv.QUOTE_NONE,
        on_bad_lines="warn"
    )

    for bloco, chunk in enumerate(leitor, start=1):
        # 1. Limpeza de caracteres ruidosos
        chunk = chunk.replace('"', '', regex=True)

        # 2. Filtro de Situação Cadastral: '02' é o código para ATIVA
        # Usamos .str.strip() para capturar apenas as ativas
        ativos = chunk[chunk["situacao_cadastral"].str.strip() == "02"].copy()

        qtd_ativos_bloco = len(ativos)
        total_ativos += qtd_ativos_bloco

        if qtd_ativos_bloco > 0:
            # 3. Exportação Incremental (Append) em UTF-8
            ativos.to_csv(
                ARQUIVO_SAIDA,
                mode="a",
                header=primeira_escrita,
                index=False,
                sep=";",
                encoding="utf-8"
            )
            primeira_escrita = False

        # Feedback em tempo real
        print(f"   - Bloco {bloco:>3} | Ativas no bloco: {qtd_ativos_bloco:>7,} | Total: {total_ativos:,}")

tempo_final = (time.time() - inicio_total) / 60

print(f"\n{'='*60}")
print(f"RESULTADO FINAL")
print(f"{'='*60}")
print(f"Local do Arquivo Gerado: {ARQUIVO_SAIDA}")
print(f"Total de registros ativos encontrados: {total_ativos:,}")
print(f"Tempo de execução: {tempo_final:.2f} minutos")