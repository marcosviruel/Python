import duckdb
import pandas as pd
import os
import time
import re

# ================= CONFIGURAÇÕES DE CAMINHO =================
PASTA_RAIZ = r"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python\CSVs"
PATH_REDE_BRUTA = os.path.join(PASTA_RAIZ, "Rede_Credenciada_Supermercado.csv")
PASTA_BASES_UF = os.path.join(PASTA_RAIZ, "3_Bases_Empresas_Estaduais")
PASTA_SAIDA_LEADS = os.path.join(PASTA_RAIZ, "4_Leads_Comerciais_Estado")
os.makedirs(PASTA_SAIDA_LEADS, exist_ok=True)

inicio = time.time()
con = duckdb.connect()

print("--- [PASSO 1] Carregando Rede de Supermercados ---")

if os.path.exists(PATH_REDE_BRUTA):
    # Lendo a rede de mercados para saber quem são os vizinhos
    df_rede = pd.read_csv(PATH_REDE_BRUTA, sep=';', encoding='latin1', dtype=str)
    df_rede.columns = [col.strip().upper() for col in df_rede.columns]
    
    # Criamos o CLUSTER (5 primeiros dígitos do CEP) para o Join geográfico
    df_rede['CEP_CLUSTER'] = df_rede['CEP'].str.replace(r'\D', '', regex=True).str.zfill(8).str.slice(0, 5)
    con.register('tabela_rede', df_rede)
    print(f"Rede carregada: {len(df_rede)} supermercados parceiros.")
else:
    print(f"ERRO: Arquivo da rede não encontrado em {PATH_REDE_BRUTA}!")
    exit()

print("--- [PASSO 2] Cruzando Geo-Proximidade + Inteligência Comercial ---")

todos_arquivos = os.listdir(PASTA_BASES_UF)
arquivos_uf = sorted(list(set([f for f in todos_arquivos if re.search(r'Empresas_[A-Z]{2}\.csv$', f)])))

for arquivo in arquivos_uf:
    uf = arquivo.split('_')[-1].replace('.csv', '')
    path_leitura = os.path.join(PASTA_BASES_UF, arquivo).replace('\\', '/')
    path_escrita = os.path.join(PASTA_SAIDA_LEADS, f"Leads_Comercial_{uf}.csv").replace('\\', '/')
    
    print(f"   -> Filtrando vizinhos e classificando: {uf}")
    
    # QUERY ATUALIZADA: Incluindo as novas colunas de potencial e CNAEs
    query_join = f"""
        SELECT 
            e.ranking_potencial,    -- O Ranking DIAMANTE/OURO que criamos
            e.razao_social,
            e.nome_fantasia,
            e.cnae_principal,       -- Saber se é indústria, serviço, etc.
            e.cnae_secundario,      -- Detalhes da operação
            e.capital_social,       -- Poder financeiro
            e.email,
            e.ddd_1 AS ddd1,
            e.telefone_1 AS telefone1,
            e.ddd_2 AS ddd2,
            e.telefone_2 AS telefone2,
            e.uf,
            e.nome_municipio_real,
            e.bairro,
            e.logradouro,
            e.numero,
            e.cep,
            r.FANTASIA AS SUPERMERCADO_PROXIMO,
            r.ENDERECO AS ENDERECO_SUPERMERCADO,
            e.cnpj_basico,
            e.cnpj_ordem,
            e.cnpj_dv
        FROM read_csv_auto('{path_leitura}', 
                           sep=';', 
                           all_varchar=True, 
                           quote='', 
                           ignore_errors=True) e
        INNER JOIN tabela_rede r 
            ON (LEFT(CAST(e.cep AS VARCHAR), 5) = r.CEP_CLUSTER)
        ORDER BY e.ranking_potencial ASC -- Garante os Campeões no topo do arquivo
    """
    
    try:
        con.execute(f"COPY ({query_join}) TO '{path_escrita}' (HEADER, DELIMITER ';')")
    except Exception as e:
        print(f"      [AVISO] Erro no processamento de {uf}: {e}")

con.close()
print("-" * 60)
print(f"✅ PROCESSO FINALIZADO!")
print(f"Os leads estão prontos na pasta: {PASTA_SAIDA_LEADS}")
print(f"Tempo total: {(time.time() - inicio)/60:.2f} MINUTOS")