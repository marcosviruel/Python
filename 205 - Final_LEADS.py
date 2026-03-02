import pandas as pd
import os
import json
import re
import unicodedata
from rapidfuzz import process

# ================= CONFIGURAÇÕES DE AMBIENTE =================
PASTA_RAIZ = r"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python\CSVs"
DIRETORIO_DO_SCRIPT = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_CONFIG = os.path.join(DIRETORIO_DO_SCRIPT, "config_farmacia.json")

# Ordem padrão para os arquivos de Bairro
COLUNAS_BAIRRO = [
    "bairro_corrigido", "razao_social", "qtde_parceiros_bairro", 
    "qtde_parceiros_cidade", "email", "ddd_1", "telefone_1", 
    "ddd_2", "telefone_2", "cep", "logradouro", "numero", "lista_farmacias_total"
]

# Ordem específica para o arquivo Consolidado (Cidade antes de Bairro)
COLUNAS_CONSOLIDADO = [
    "bairro_corrigido", "razao_social", "qtde_parceiros_cidade", 
    "qtde_parceiros_bairro", "email", "ddd_1", "telefone_1", 
    "ddd_2", "telefone_2", "cep", "logradouro", "numero", "lista_farmacias_total"
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

PASTA_ORIGEM = os.path.join(PASTA_RAIZ, CONFIG['PASTA_BASE'])
nome_arquivo_uf = f"Leads_Comercial_{CONFIG['UF'].upper()}.csv"
ARQUIVO_ENTRADA = os.path.join(PASTA_ORIGEM, nome_arquivo_uf)

PASTA_SAIDA = os.path.join(PASTA_ORIGEM, CONFIG['UF'].upper(), CONFIG['CIDADE'].upper())
os.makedirs(PASTA_SAIDA, exist_ok=True)

# ================= PASSO 1: FILTRAGEM E LIMPEZA =================
print(f"--- [PASSO 1] Filtrando leads de {CONFIG['CIDADE']} ---")

chunks = pd.read_csv(ARQUIVO_ENTRADA, sep=';', dtype=str, chunksize=50000)
blocos = []
cidade_alvo = limpar_texto_universal(CONFIG['CIDADE'])

for chunk in chunks:
    chunk.columns = [c.lower().strip() for c in chunk.columns]
    mask_cidade = chunk['nome_municipio_real'].apply(limpar_texto_universal) == cidade_alvo
    df_temp = chunk[mask_cidade].copy()
    if not df_temp.empty:
        df_temp = df_temp[~df_temp['natureza_juridica'].str.contains('2135|MEI', case=False, na=False)]
        blocos.append(df_temp)

if not blocos:
    print(f"Nenhum dado para {CONFIG['CIDADE']}.")
    exit()

df_base = pd.concat(blocos, ignore_index=True)

# ================= PASSO 2: INTELIGÊNCIA DE BAIRROS =================
print(f"--- [PASSO 2] Padronização de Bairros (Fuzzy Matching) ---")
df_base['bairro_limpo'] = df_base['bairro'].apply(limpar_texto_universal)

contagem = df_base['bairro_limpo'].value_counts()
BAIRROS_RELEVANTES = contagem[contagem >= CONFIG.get('MIN_LEADS_BAIRRO', 5)].index.tolist()
BAIRROS_GABARITO = BAIRROS_RELEVANTES[:CONFIG.get('TOP_N_BAIRROS', 30)]

def corrigir_bairro(nome_atual):
    nome = limpar_texto_universal(nome_atual)
    if not nome or nome == "" or not BAIRROS_GABARITO: return "OUTROS"
    match = process.extractOne(nome, BAIRROS_GABARITO, score_cutoff=CONFIG.get('SCORE_MINIMO_BAIRRO', 85))
    return match[0] if match else "OUTROS"

df_base['bairro_corrigido'] = df_base['bairro_limpo'].apply(corrigir_bairro)

# ================= PASSO 3: MÉTRICAS E AGREGAÇÃO =================
print("--- [PASSO 3] Calculando Potencial e Ordenação ---")

col_parceiro = 'farmacia_proxima' 

df_counts = df_base[['cnpj_basico', 'bairro_corrigido', col_parceiro]].drop_duplicates()
cont_b = df_counts.groupby(['cnpj_basico', 'bairro_corrigido']).size().reset_index(name='qtde_parceiros_bairro')
cont_c = df_counts.groupby('cnpj_basico').size().reset_index(name='qtde_parceiros_cidade')

df_base = pd.merge(df_base, cont_b, on=['cnpj_basico', 'bairro_corrigido'], how='left')
df_base = pd.merge(df_base, cont_c, on='cnpj_basico', how='left')

agg_farmas = df_base.groupby('cnpj_basico')[col_parceiro].agg(
    lista_farmacias_total=lambda x: ' | '.join(sorted(set(x.astype(str)))[:15])
).reset_index()

df_final = df_base.drop_duplicates(subset=['cnpj_basico']).copy()
df_final = pd.merge(df_final.drop(columns=[col_parceiro], errors='ignore'), 
                    agg_farmas, on='cnpj_basico', how='left')

df_final['qtde_parceiros_bairro'] = df_final['qtde_parceiros_bairro'].fillna(0).astype(int)
df_final['qtde_parceiros_cidade'] = df_final['qtde_parceiros_cidade'].fillna(0).astype(int)

# ================= PASSO 4: EXPORTAÇÃO COM ORDENAÇÃO =================
print("--- [PASSO 4] Exportando Arquivos Ordenados ---")

# 1. CONSOLIDADO: Ordenado por Cidade (Decrescente) e com colunas invertidas
df_consolidado = df_final.sort_values(by='qtde_parceiros_cidade', ascending=False)
df_consolidado[COLUNAS_CONSOLIDADO].to_csv(
    os.path.join(PASTA_SAIDA, f"00_CONSOLIDADO_{CONFIG['CIDADE'].upper()}.csv"), 
    sep=';', index=False, encoding='utf-8-sig', decimal=',')

# 2. POR BAIRRO: Ordenado por Bairro (Decrescente)
for bairro in df_final['bairro_corrigido'].unique():
    df_b = df_final[df_final['bairro_corrigido'] == bairro].copy()
    df_b = df_b.sort_values(by='qtde_parceiros_bairro', ascending=False)
    
    bairro_seguro = limpar_nome_arquivo(bairro)
    nome_f = f"Leads_{CONFIG['CIDADE'].upper()}_{bairro_seguro}.csv"
    df_b[COLUNAS_BAIRRO].to_csv(os.path.join(PASTA_SAIDA, nome_f), 
                                  sep=';', index=False, encoding='utf-8-sig', decimal=',')

# 3. RANKING
ranking = df_final.groupby('bairro_corrigido').agg(
    total_leads=('cnpj_basico', 'count'),
    potencial_medio=('qtde_parceiros_bairro', 'mean')
).reset_index().round(2).sort_values(by='potencial_medio', ascending=False)
ranking.to_csv(os.path.join(PASTA_SAIDA, f"00_RANKING_BAIRROS_{CONFIG['CIDADE'].upper()}.csv"), 
                sep=';', index=False, encoding='utf-8-sig', decimal=',')

print(f"\n✅ SUCESSO! Consolidado atualizado com qtde_parceiros_cidade em destaque.")