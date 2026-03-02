import pandas as pd
import glob
import os
import csv

# ================= CONFIGURAÇÕES DE CAMINHO =================
PASTA_RAIZ = r"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python\CSVs"
PASTA_ORIGEM_EMPRESAS = os.path.join(PASTA_RAIZ, "Empresas")
SAIDA_EMPRESAS_LIMPAS = os.path.join(PASTA_RAIZ, "2_Empresas_Filtradas.csv")

# ================= FUNÇÃO DE RANKING (NOME ATUALIZADO) =================
def classificar_prioridade(row):
    try:
        cap = float(row['capital_social'])
    except:
        cap = 0.0
    
    # Normaliza porte: remove espaços e garante 2 dígitos
    porte = str(row['porte_empresa']).strip().zfill(2)
    
    # Lógica de Ranking com nome solicitado: "1 - DIAMANTE - Campeao"
    if porte == '05' and cap >= 1000000:
        return '1 - DIAMANTE - Campeao'
    elif porte == '05' or cap >= 1000000:
        return '2 - OURO - Prioridade Alta'
    elif porte == '03' and cap >= 100000:
        return '3 - PRATA - Bom Potencial'
    else:
        return '4 - BRONZE - Menor Potencial'

# ================= LIMPEZA PRELIMINAR =================
if os.path.exists(SAIDA_EMPRESAS_LIMPAS):
    os.remove(SAIDA_EMPRESAS_LIMPAS)
    print(f"[*] Arquivo antigo removido para atualização de nomenclatura.")

print("--- [PASSO 2] QUALIFICANDO LEADS: FOCO DIAMANTE CAMPEAO ---")
print("-" * 60)

arquivos_empresas = glob.glob(os.path.join(PASTA_ORIGEM_EMPRESAS, "Empresas*.csv"))

if not arquivos_empresas:
    print(f"❌ ERRO: Arquivos não encontrados em: {PASTA_ORIGEM_EMPRESAS}")
else:
    primeira_escrita = True
    total_final = 0

    for arquivo in arquivos_empresas:
        print(f"Lendo: {os.path.basename(arquivo)}...")
        
        leitor = pd.read_csv(
            arquivo, 
            sep=";", 
            header=None, 
            usecols=[0, 1, 2, 4, 5], 
            dtype=str, 
            encoding="latin1", 
            chunksize=500000,
            quoting=csv.QUOTE_NONE
        )
        
        for chunk in leitor:
            # 1. Limpeza de colunas e remoção de aspas/espaços
            chunk.columns = ['cnpj_basico', 'razao_social', 'natureza_juridica', 'capital_social', 'porte_empresa']
            for col in chunk.columns:
                chunk[col] = chunk[col].str.replace('"', '', regex=False).str.strip()

            # 2. FILTROS (Grupo 2, sem MEI, apenas Porte 03 e 05)
            chunk = chunk[chunk['natureza_juridica'].str.startswith('2', na=False)]
            chunk = chunk[chunk['natureza_juridica'] != '2135']
            
            chunk['porte_limpo'] = chunk['porte_empresa'].str.zfill(2)
            chunk = chunk[chunk['porte_limpo'].isin(['03', '05'])]
            
            if not chunk.empty:
                # 3. Tratamento Numérico do Capital Social
                chunk['capital_social'] = (
                    chunk['capital_social']
                    .str.replace(',', '.', regex=False)
                    .fillna('0')
                )
                chunk['capital_social'] = pd.to_numeric(chunk['capital_social'], errors='coerce').fillna(0)

                # 4. Aplicação do Ranking Atualizado
                chunk['ranking_potencial'] = chunk.apply(classificar_prioridade, axis=1)

                # 5. Remoção do .0 (Inteiro)
                chunk['capital_social'] = chunk['capital_social'].astype(int)

                # 6. Exportação Final
                colunas_finais = ['cnpj_basico', 'razao_social', 'natureza_juridica', 'capital_social', 'porte_empresa', 'ranking_potencial']
                chunk[colunas_finais].to_csv(
                    SAIDA_EMPRESAS_LIMPAS, 
                    mode='a', 
                    index=False, 
                    header=primeira_escrita, 
                    sep=';', 
                    encoding='utf-8'
                )
                primeira_escrita = False
                total_final += len(chunk)

    print("-" * 60)
    print(f"✅ SUCESSO! {total_final:,} empresas classificadas.".replace(',', '.'))