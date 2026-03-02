import pandas as pd
import os
import time
import csv

# ================= CONFIGURAÇÕES DE AMBIENTE =================
PASTA_RAIZ = r"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python\CSVs"
PASTA_ORIGEM_BRUTOS = os.path.join(PASTA_RAIZ, "Estabelecimentos")
ARQUIVO_SAIDA = os.path.join(PASTA_RAIZ, "1_Estabelecimentos_Ativos_Brasil.csv")

CHUNKSIZE = 500_000
ENCODING_ORIGEM = "latin1"
SEPARADOR_ORIGEM = ";"

# Mapeamento técnico atualizado (Incluindo coluna 12 - CNAE Secundário)
MAPA_COLUNAS = {
    0: "cnpj_basico", 1: "cnpj_ordem", 2: "cnpj_dv", 3: "matriz_filial", 
    4: "nome_fantasia", 5: "situacao_cadastral", 10: "data_inicio", 
    11: "cnae_principal", 12: "cnae_secundario", 13: "tipo_logradouro", 
    14: "logradouro", 15: "numero", 16: "complemento", 17: "bairro", 
    18: "cep", 19: "uf", 20: "municipio", 21: "ddd_1", 22: "telefone_1", 
    23: "ddd_2", 24: "telefone_2", 27: "email"
}

COLUNAS_PARA_LER = list(MAPA_COLUNAS.keys())
NOMES_COLUNAS = list(MAPA_COLUNAS.values())

# Lista de CNAEs de Supermercados/Minimercados para EXCLUSÃO (Negativação)
CNAES_EXCLUIR = ['4711301', '4711302', '4712100']

# ================= FUNÇÕES DE APOIO =================

def limpar_arquivo_antigo(caminho):
    if os.path.exists(caminho):
        os.remove(caminho)
        print(f"[*] Arquivo antigo removido: {os.path.basename(caminho)}")

# ================= EXECUÇÃO PRINCIPAL =================

inicio_total = time.time()
total_ativos = 0
primeira_escrita = True

if not os.path.exists(PASTA_RAIZ):
    os.makedirs(PASTA_RAIZ)

limpar_arquivo_antigo(ARQUIVO_SAIDA)

print(f"\n{'='*60}")
print("FILTRAGEM: ATIVOS + REMOÇÃO DE CONCORRENTES (MERCADOS)")
print(f"{'='*60}\n")

for i in range(10):
    arquivo_nome = f"Estabelecimentos{i}.csv"
    caminho_input = os.path.join(PASTA_ORIGEM_BRUTOS, arquivo_nome)

    if not os.path.exists(caminho_input):
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

        # 2. FILTRO DE ATIVAS (Mantido conforme solicitado)
        ativos = chunk[chunk["situacao_cadastral"].str.strip() == "02"].copy()

        if not ativos.empty:
            # 3. FILTRO DE CONCORRENTES (NEGATIVAÇÃO)
            # Remove se o Principal estiver na lista
            ativos = ativos[~ativos["cnae_principal"].isin(CNAES_EXCLUIR)]
            
            # Remove se o Secundário contiver algum dos CNAEs (busca textual pois secundário é uma lista)
            # Criamos uma máscara para identificar quem tem esses códigos no campo de texto secundário
            padrao_exclusao = '|'.join(CNAES_EXCLUIR)
            ativos = ativos[~ativos["cnae_secundario"].str.contains(padrao_exclusao, na=False)]

            qtd_final_bloco = len(ativos)
            total_ativos += qtd_final_bloco

            if qtd_final_bloco > 0:
                # 4. Exportação Incremental
                ativos.to_csv(
                    ARQUIVO_SAIDA,
                    mode="a",
                    header=primeira_escrita,
                    index=False,
                    sep=";",
                    encoding="utf-8"
                )
                primeira_escrita = False

        print(f"   - Bloco {bloco:>3} | Leads Válidos no bloco: {len(ativos):>7,} | Total Acumulado: {total_ativos:,}")

tempo_final = (time.time() - inicio_total) / 60

print(f"\n{'='*60}")
print(f"RESULTADO FINAL")
print(f"Local: {ARQUIVO_SAIDA}")
print(f"Total de Leads (Ativos e Não-Mercados): {total_ativos:,}")
print(f"Tempo: {tempo_final:.2f} minutos")