import duckdb
import os
import time

# ================= CONFIGURAÇÕES DE CAMINHO =================
PASTA_RAIZ = r"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python\CSVs"

ARQUIVO_ESTAB = os.path.join(PASTA_RAIZ, "1_Estabelecimentos_Ativos_Brasil.csv")
ARQUIVO_EMPRESAS_LIMPAS = os.path.join(PASTA_RAIZ, "2_Empresas_Filtradas.csv")
ARQUIVO_MUNICIPIOS = os.path.join(PASTA_RAIZ, "Municipios", "Municipios.csv")

PASTA_DESTINO_FINAL = os.path.join(PASTA_RAIZ, "3_Bases_Empresas_Estaduais")
os.makedirs(PASTA_DESTINO_FINAL, exist_ok=True)

ESTADOS_REAIS = ['AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG',
                 'PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO']

# =================================================

inicio = time.time()
print("=" * 60)
print("SCRIPT FINAL: CRUZAMENTO + RANKING + EXPORTAÇÃO POR UF")
print("=" * 60)

con = duckdb.connect()

# Padronização de caminhos para o DuckDB (SQL usa barra normal)
path_estab = ARQUIVO_ESTAB.replace('\\', '/')
path_emp = ARQUIVO_EMPRESAS_LIMPAS.replace('\\', '/')
path_mun = ARQUIVO_MUNICIPIOS.replace('\\', '/')

# Configurações de leitura
csv_config = "sep=';', quote='\"', ignore_errors=True, all_varchar=True"
# Para o Município, definimos as colunas explicitamente
csv_mun_config = "sep=';', quote='\"', ignore_errors=True, header=False, columns={'cod_m': 'VARCHAR', 'nome_m': 'VARCHAR'}"

# A QUERY ATUALIZADA: Incluindo Capital Social e Ranking Potencial
query_processamento = f"""
    WITH mun_limpo AS (
        SELECT 
            REPLACE(cod_m, '"', '') as cod_m, 
            REPLACE(nome_m, '"', '') as nome_m 
        FROM read_csv_auto('{path_mun}', {csv_mun_config})
    )
    SELECT 
        e.*, 
        emp.razao_social,
        emp.natureza_juridica,
        emp.capital_social,     -- ADICIONADO
        emp.ranking_potencial,  -- ADICIONADO
        m.nome_m AS nome_municipio_real
    FROM read_csv_auto('{path_estab}', {csv_config}) e
    INNER JOIN read_csv_auto('{path_emp}', {csv_config}) emp 
        ON (REPLACE(e.cnpj_basico, '"', '') = REPLACE(emp.cnpj_basico, '"', ''))
    LEFT JOIN mun_limpo m 
        ON (TRY_CAST(REPLACE(e.municipio, '"', '') AS INTEGER) = TRY_CAST(m.cod_m AS INTEGER))
    WHERE e.uf IN ({str(ESTADOS_REAIS)[1:-1]})
"""

try:
    print(f"[{time.strftime('%H:%M:%S')}] Iniciando processamento pesado com DuckDB...")
    con.execute(f"CREATE OR REPLACE VIEW dados_finais AS {query_processamento}")
    
    print(f"[{time.strftime('%H:%M:%S')}] Verificando estados disponíveis...")
    ufs_encontradas = [row[0] for row in con.execute("SELECT DISTINCT uf FROM dados_finais ORDER BY uf").fetchall()]
    
    print(f"Estados identificados: {len(ufs_encontradas)}")
    print("-" * 60)

    for uf in ufs_encontradas:
        if uf in ESTADOS_REAIS:
            nome_arquivo = f"Empresas_{uf}.csv"
            caminho_saida = os.path.join(PASTA_DESTINO_FINAL, nome_arquivo).replace('\\', '/')
            
            # Ordenamos por Ranking para que os "Campeões" fiquem no topo do arquivo de cada estado
            con.execute(f"""
                COPY (SELECT * FROM dados_finais WHERE uf = '{uf}' ORDER BY ranking_potencial ASC) 
                TO '{caminho_saida}' (HEADER, DELIMITER ';')
            """)
            print(f"   -> [CONCLUÍDO] {nome_arquivo}")

except Exception as e:
    print("\n--- ERRO NA EXECUÇÃO SQL ---")
    print(f"Mensagem: {str(e)}")

fim = time.time()
print("-" * 60)
print(f"PROCESSO TOTAL FINALIZADO EM: {(fim - inicio)/60:.2f} MINUTOS")