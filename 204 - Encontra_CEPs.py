import duckdb
import pandas as pd
import os
import re
import time

# ================= 1. CONFIGURAÇÕES =================
PASTA_RAIZ = r"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python\CSVs"
PATH_ENRIQUECIDA = os.path.join(PASTA_RAIZ, "Rede_Farmacia_Com_CEP_Offline", "REDE_FARMACIAS_ENRIQUECIDA_FULL.csv")
PASTA_BASES_UF = os.path.join(PASTA_RAIZ, "3_Bases_Empresas_Estaduais")
PASTA_SAIDA = os.path.join(PASTA_RAIZ, "Rede_Farmacia_Com_CEP_Offline")

con = duckdb.connect()

print("--- [PASSO 1] Carregando CEPs das Farmácias Credenciadas ---")
try:
    df_credenciadas = pd.read_csv(PATH_ENRIQUECIDA, sep=';', dtype=str, encoding='utf-8-sig')
    # Pegamos o CEP e o Nome da Farmácia
    df_credenciadas = df_credenciadas[['CEP_ENCONTRADO', 'ESTABELECIMENTO']].drop_duplicates()
    con.register('base_ceps_validos', df_credenciadas)
    print(f"✅ {len(df_credenciadas)} CEPs únicos prontos para busca.")
except Exception as e:
    print(f"❌ Erro ao carregar arquivo enriquecido: {e}")
    exit()

print("\n--- [PASSO 2] Cruzando CEPs com Base da Receita (Gerando Leads) ---")
arquivos_uf = sorted([f for f in os.listdir(PASTA_BASES_UF) if re.search(r'Empresas_[A-Z]{2}\.csv$', f)])

lista_final_comercial = []

for arquivo in arquivos_uf:
    uf_sigla = re.search(r'Empresas_([A-Z]{2})\.csv', arquivo).group(1)
    path_leitura = os.path.join(PASTA_BASES_UF, arquivo).replace('\\', '/')
    print(f"-> Extraindo Leads em {uf_sigla}...", end=" ", flush=True)
    
    # AJUSTE NAS COLUNAS: Mudamos ddd1 para ddd_1, etc. conforme o erro reportado
    query = f"""
        SELECT 
            e.cnpj_basico, e.cnpj_ordem, e.cnpj_dv, e.razao_social, e.nome_fantasia,
            e.natureza_juridica, e.email, 
            e.ddd_1, e.telefone_1, e.ddd_2, e.telefone_2,
            e.uf, e.nome_municipio_real, e.logradouro, e.numero, e.bairro, e.cep,
            v.ESTABELECIMENTO as FARMACIA_PROXIMA
        FROM read_csv_auto('{path_leitura}', sep=';', all_varchar=True, quote='', ignore_errors=True) e
        INNER JOIN base_ceps_validos v ON (e.cep = v.CEP_ENCONTRADO)
        WHERE e.uf = '{uf_sigla}'
    """
    
    try:
        df_res = con.execute(query).df()
        if not df_res.empty:
            lista_final_comercial.append(df_res)
            nome_leads = f"Leads_Comercial_{uf_sigla}.csv"
            df_res.to_csv(os.path.join(PASTA_SAIDA, nome_leads), sep=';', index=False, encoding='utf-8-sig')
            print(f"✅ {len(df_res)} leads")
        else:
            print("⚠️ 0")
    except Exception as e:
        print(f"❌ Erro Técnico: {str(e)[:100]}")

# Compilação Final
if lista_final_comercial:
    df_leads_total = pd.concat(lista_final_comercial, ignore_index=True)
    path_consolidado = os.path.join(PASTA_SAIDA, "BASE_LEADS_PARA_PDF.csv")
    df_leads_total.to_csv(path_consolidado, sep=';', index=False, encoding='utf-8-sig')
    
    print("\n" + "="*50)
    print(f"RESULTADO FINAL:")
    print(f"Total de Leads extraídos: {len(df_leads_total)}")
    print(f"Arquivos gerados em: {PASTA_SAIDA}")
    print("="*50)
else:
    print("\n❌ Nenhum lead foi gerado.")

con.close()