import pandas as pd
import glob
import os
import csv

# ================= CONFIGURAÇÕES DE CAMINHO =================
# Pasta principal onde os resultados finais devem ficar
PASTA_RAIZ = r"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python\CSVs"

# Subpasta onde estão os arquivos "Empresas*.csv" originais
PASTA_ORIGEM_EMPRESAS = os.path.join(PASTA_RAIZ, "Empresas")

# Caminho do arquivo de SAÍDA (agora apontando para a PASTA_RAIZ)
SAIDA_EMPRESAS_LIMPAS = os.path.join(PASTA_RAIZ, "2_Empresas_Filtradas.csv")

# ================= LIMPEZA PRELIMINAR =================
if os.path.exists(SAIDA_EMPRESAS_LIMPAS):
    os.remove(SAIDA_EMPRESAS_LIMPAS)

print("PASSO 2: FILTRANDO RAZÃO SOCIAL E NATUREZA JURÍDICA")
print(f"Salvando resultado em: {PASTA_RAIZ}")
print("-" * 60)

# Buscamos os arquivos dentro da subpasta /Empresas
arquivos_empresas = glob.glob(os.path.join(PASTA_ORIGEM_EMPRESAS, "Empresas*.csv"))

if not arquivos_empresas:
    print(f"ERRO: Nenhum arquivo 'Empresas*.csv' encontrado em: {PASTA_ORIGEM_EMPRESAS}")
else:
    primeira_escrita = True
    for arquivo in arquivos_empresas:
        print(f"Processando: {os.path.basename(arquivo)}")
        
        leitor = pd.read_csv(
            arquivo, 
            sep=";", 
            header=None, 
            usecols=[0, 1, 2], 
            dtype=str, 
            encoding="latin1", 
            chunksize=500000,
            quoting=csv.QUOTE_NONE
        )
        
        for chunk in leitor:
            # Limpa aspas
            chunk = chunk.apply(lambda x: x.str.replace('"', '', regex=False))
            
            # Renomeia
            chunk.columns = ['cnpj_basico', 'razao_social', 'natureza_juridica']
            
            # FILTRO: Apenas Naturezas Jurídicas que começam com '2'
            chunk = chunk[chunk['natureza_juridica'].str.startswith('2', na=False)]
            
            if not chunk.empty:
                chunk.to_csv(
                    SAIDA_EMPRESAS_LIMPAS, 
                    mode='a', 
                    index=False, 
                    header=primeira_escrita, 
                    sep=';', 
                    encoding='utf-8'
                )
                primeira_escrita = False

    print(f"\nSucesso! O arquivo '2_Empresas_Filtradas.csv' foi gerado na pasta: {PASTA_RAIZ}")