import pandas as pd
import os
import json
import re
import unicodedata
from rapidfuzz import process

# ================= CONFIGURAÇÕES DE AMBIENTE =================
PASTA_RAIZ = r"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python\CSVs"
DIRETORIO_DO_SCRIPT = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_CONFIG = os.path.join(DIRETORIO_DO_SCRIPT, "config.json")

# Colunas na ordem exata solicitada
COLUNAS_VENDEDOR = [
    "bairro_corrigido", "razao_social", "qtde_parceiros_bairro", 
    "qtde_parceiros_cidade", "email", "ddd1", "telefone1", 
    "ddd2", "telefone2", "cep", "logradouro", "numero", "lista_supermercados_total"
]

def limpar_texto_universal(txt):
    if pd.isna(txt): return ""
    txt = unicodedata.normalize('NFKD', str(txt)).encode('ASCII', 'ignore').decode('ASCII')
    return re.sub(r'[^A-Z0-9\s]', '', txt.upper()).strip()

def limpar_nome_arquivo(nome):
    return re.sub(r'[\\/*?:"<>|]', '', str(nome)).strip().replace(" ", "_")

# ================= CARREGAMENTO DE CONFIGURAÇÃO =================
with open(ARQUIVO_CONFIG, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

nome_arquivo_uf = f"Leads_Comercial_{CONFIG['UF'].upper()}.csv"
ARQUIVO_ENTRADA = os.path.join(PASTA_RAIZ, "4_Leads_Comerciais_Estado", nome_arquivo_uf)
PASTA_SAIDA = os.path.join(PASTA_RAIZ, "5_Segmenta_Cidade_Bairro", CONFIG['UF'].upper(), CONFIG['CIDADE'].upper())
os.makedirs(PASTA_SAIDA, exist_ok=True)

# ================= PASSO 1: FILTRAGEM E LIMPEZA =================
print(f"--- [PASSO 1] Filtrando leads de {CONFIG['CIDADE']} ---")

chunks = pd.read_csv(ARQUIVO_ENTRADA, sep=';', dtype=str, chunksize=100000)
blocos = []
cidade_alvo = limpar_texto_universal(CONFIG['CIDADE'])

for chunk in chunks:
    chunk.columns = [c.lower().strip() for c in chunk.columns]
    # Caso a coluna seja nome_municipio_real ou municipio
    col_cid = 'nome_municipio_real' if 'nome_municipio_real' in chunk.columns else 'municipio'
    
    mask_cidade = chunk[col_cid].apply(limpar_texto_universal) == cidade_alvo
    df_temp = chunk[mask_cidade].copy()
    
    if not df_temp.empty:
        # Filtro de Natureza Jurídica (Remove MEI e similares)
        df_temp = df_temp[~df_temp['natureza_juridica'].str.contains('2135|MEI', case=False, na=False)]
        blocos.append(df_temp)

if not blocos:
    print(f"Nenhum dado para {CONFIG['CIDADE']}.")
    exit()

df_base = pd.concat(blocos, ignore_index=True)

# ================= PASSO 2: INTELIGÊNCIA DE BAIRROS =================
print(f"--- [PASSO 2] Padronização de Bairros (Fuzzy Matching) ---")
df_base['bairro_limpo'] = df_base['bairro'].apply(limpar_texto_universal)

# Define gabarito de bairros relevantes
min_leads = CONFIG.get('MIN_LEADS_BAIRRO', 10)
contagem = df_base['bairro_limpo'].value_counts()
BAIRROS_RELEVANTES = contagem[contagem >= min_leads].index.tolist()
BAIRROS_GABARITO = BAIRROS_RELEVANTES[:CONFIG['TOP_N_BAIRROS']]

def corrigir_bairro(nome_atual):
    nome = limpar_texto_universal(nome_atual)
    if not nome or nome == "": return "OUTROS"
    match = process.extractOne(nome, BAIRROS_GABARITO, score_cutoff=CONFIG['SCORE_MINIMO_BAIRRO'])
    return match[0] if match else "OUTROS"

df_base['bairro_corrigido'] = df_base['bairro_limpo'].apply(corrigir_bairro)

# ================= PASSO 3: MÉTRICAS E AGREGAÇÃO =================
print("--- [PASSO 3] Agregando Supermercados e Calculando Potencial ---")

# Unifica colunas de interesse para contagem
col_parceiro = 'supermercado_proximo' if 'supermercado_proximo' in df_base.columns else 'supermercado_proximo'

df_counts = df_base[['cnpj_basico', 'bairro_corrigido', col_parceiro]].drop_duplicates()
cont_b = df_counts.groupby(['cnpj_basico', 'bairro_corrigido']).size().reset_index(name='qtde_parceiros_bairro')
cont_c = df_counts.groupby('cnpj_basico').size().reset_index(name='qtde_parceiros_cidade')

df_base = pd.merge(df_base, cont_b, on=['cnpj_basico', 'bairro_corrigido'], how='left')
df_base = pd.merge(df_base, cont_c, on='cnpj_basico', how='left')

# Agregação da lista de supermercados em uma única string
agg_supers = df_base.groupby('cnpj_basico')[col_parceiro].agg(
    lista_supermercados_total=lambda x: ' | '.join(sorted(set(x.astype(str)))[:15])
).reset_index()

df_final = df_base.drop_duplicates(subset=['cnpj_basico']).copy()
df_final = pd.merge(df_final.drop(columns=[col_parceiro, 'lista_supermercados_total'], errors='ignore'), 
                    agg_supers, on='cnpj_basico', how='left')

df_final['qtde_parceiros_bairro'] = df_final['qtde_parceiros_bairro'].fillna(0).astype(int)
df_final['qtde_parceiros_cidade'] = df_final['qtde_parceiros_cidade'].fillna(0).astype(int)

# ================= PASSO 4: EXPORTAÇÃO FINAL =================
print("--- [PASSO 4] Exportando Arquivos ---")

# 1. RANKING ESTRATÉGICO (Arquivo que estava faltando)
ranking = df_final.groupby('bairro_corrigido').agg(
    total_leads=('cnpj_basico', 'count'),
    media_parceiros_bairro=('qtde_parceiros_bairro', 'mean')
).reset_index().round(2).sort_values(by='media_parceiros_bairro', ascending=False)
ranking['prioridade'] = range(1, len(ranking) + 1)
ranking.to_csv(os.path.join(PASTA_SAIDA, f"00_RANKING_BAIRROS_{CONFIG['CIDADE'].upper()}.csv"), 
               sep=';', index=False, encoding='utf-8-sig', decimal=',')

# 2. CONSOLIDADO (Ordenado por potencial na CIDADE)
df_consolidado = df_final.sort_values(by='qtde_parceiros_cidade', ascending=False)
df_consolidado[COLUNAS_VENDEDOR].to_csv(os.path.join(PASTA_SAIDA, f"00_CONSOLIDADO_{CONFIG['CIDADE'].upper()}.csv"), 
                                        sep=';', index=False, encoding='utf-8-sig', decimal=',')

# 3. Arquivos por Bairro (Sem pasta "outros", tudo na mesma raiz)
for bairro in df_final['bairro_corrigido'].unique():
    df_b = df_final[df_final['bairro_corrigido'] == bairro].copy()
    df_b = df_b.sort_values(by='qtde_parceiros_bairro', ascending=False)
    
    bairro_seguro = limpar_nome_arquivo(bairro)
    nome_f = f"Leads_{CONFIG['CIDADE'].upper()}_{bairro_seguro}.csv"
    
    df_b[COLUNAS_VENDEDOR].to_csv(os.path.join(PASTA_SAIDA, nome_f), 
                                  sep=';', index=False, encoding='utf-8-sig', decimal=',')

print(f"\n✅ SUCESSO! Resultados exportados para: {PASTA_SAIDA}")