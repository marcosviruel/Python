import pandas as pd
import os
import json
import re
import unicodedata
from rapidfuzz import process

# ================= CONFIGURAÇÕES DE AMBIENTE =================
PASTA_RAIZ = r"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python\CSVs"
# Ajuste de segurança para o diretório do script
DIRETORIO_DO_SCRIPT = os.path.dirname(os.path.abspath(__file__)) if "__file__" in locals() else os.getcwd()
ARQUIVO_CONFIG = os.path.join(DIRETORIO_DO_SCRIPT, "config.json")

# COLUNAS ATUALIZADAS: Incluindo Inteligência Comercial e Geográfica
COLUNAS_VENDEDOR = [
    "ranking_potencial", "razao_social", "capital_social", "cnae_principal",
    "bairro_corrigido", "qtde_parceiros_bairro", "qtde_parceiros_cidade", 
    "email", "ddd1", "telefone1", "ddd2", "telefone2", 
    "cep", "logradouro", "numero", "lista_supermercados_total"
]

def limpar_texto_universal(txt):
    if pd.isna(txt): return ""
    txt = unicodedata.normalize('NFKD', str(txt)).encode('ASCII', 'ignore').decode('ASCII')
    return re.sub(r'[^A-Z0-9\s]', '', txt.upper()).strip()

def limpar_nome_arquivo(nome):
    return re.sub(r'[\\/*?:"<>|]', '', str(nome)).strip().replace(" ", "_")

# ================= CARREGAMENTO DE CONFIGURAÇÃO =================
if not os.path.exists(ARQUIVO_CONFIG):
    print(f"ERRO: config.json não encontrado em {DIRETORIO_DO_SCRIPT}")
    exit()

with open(ARQUIVO_CONFIG, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

nome_arquivo_uf = f"Leads_Comercial_{CONFIG['UF'].upper()}.csv"
ARQUIVO_ENTRADA = os.path.join(PASTA_RAIZ, "4_Leads_Comerciais_Estado", nome_arquivo_uf)
PASTA_SAIDA = os.path.join(PASTA_RAIZ, "5_Segmenta_Cidade_Bairro", CONFIG['UF'].upper(), CONFIG['CIDADE'].upper())
os.makedirs(PASTA_SAIDA, exist_ok=True)

# ================= PASSO 1: FILTRAGEM E LIMPEZA =================
print(f"--- [PASSO 1] Filtrando leads de {CONFIG['CIDADE']} ({CONFIG['UF']}) ---")

chunks = pd.read_csv(ARQUIVO_ENTRADA, sep=';', dtype=str, chunksize=100000)
blocos = []
cidade_alvo = limpar_texto_universal(CONFIG['CIDADE'])

for chunk in chunks:
    chunk.columns = [c.lower().strip() for c in chunk.columns]
    
    # Identifica a coluna de cidade (nome_municipio_real vem do Passo anterior)
    col_cid = 'nome_municipio_real' if 'nome_municipio_real' in chunk.columns else 'municipio'
    
    mask_cidade = chunk[col_cid].apply(limpar_texto_universal) == cidade_alvo
    df_temp = chunk[mask_cidade].copy()
    
    if not df_temp.empty:
        blocos.append(df_temp)

if not blocos:
    print(f"❌ Nenhum dado encontrado para a cidade: {CONFIG['CIDADE']}.")
    exit()

df_base = pd.concat(blocos, ignore_index=True)

# ================= PASSO 2: PADRONIZAÇÃO DE BAIRROS =================
print(f"--- [PASSO 2] Padronização de Bairros (Fuzzy Matching) ---")
df_base['bairro_limpo'] = df_base['bairro'].apply(limpar_texto_universal)

# Define gabarito de bairros baseado na frequência
min_leads = CONFIG.get('MIN_LEADS_BAIRRO', 10)
contagem = df_base['bairro_limpo'].value_counts()
BAIRROS_RELEVANTES = contagem[contagem >= min_leads].index.tolist()
BAIRROS_GABARITO = BAIRROS_RELEVANTES[:CONFIG.get('TOP_N_BAIRROS', 50)]

def corrigir_bairro(nome_atual):
    nome = limpar_texto_universal(nome_atual)
    if not nome or nome == "": return "OUTROS"
    match = process.extractOne(nome, BAIRROS_GABARITO, score_cutoff=CONFIG.get('SCORE_MINIMO_BAIRRO', 80))
    return match[0] if match else "OUTROS"

df_base['bairro_corrigido'] = df_base['bairro_limpo'].apply(corrigir_bairro)

# ================= PASSO 3: MÉTRICAS E AGREGAÇÃO =================
print("--- [PASSO 3] Agregando Vizinhos e Consolidando Inteligência ---")

# Coluna de supermercados vinda do Passo 4
col_parceiro = 'supermercado_proximo'

# Cálculo de densidade de parceiros por empresa
df_counts = df_base[['cnpj_basico', 'bairro_corrigido', col_parceiro]].drop_duplicates()
cont_b = df_counts.groupby(['cnpj_basico', 'bairro_corrigido']).size().reset_index(name='qtde_parceiros_bairro')
cont_c = df_counts.groupby('cnpj_basico').size().reset_index(name='qtde_parceiros_cidade')

df_base = pd.merge(df_base, cont_b, on=['cnpj_basico', 'bairro_corrigido'], how='left')
df_base = pd.merge(df_base, cont_c, on='cnpj_basico', how='left')

# Consolida a lista de nomes dos supermercados parceiros próximos
agg_supers = df_base.groupby('cnpj_basico')[col_parceiro].agg(
    lista_supermercados_total=lambda x: ' | '.join(sorted(set(x.astype(str)))[:15])
).reset_index()

df_final = df_base.drop_duplicates(subset=['cnpj_basico']).copy()
df_final = pd.merge(df_final.drop(columns=[col_parceiro, 'lista_supermercados_total'], errors='ignore'), 
                    agg_supers, on='cnpj_basico', how='left')

# ================= PASSO 4: EXPORTAÇÃO COM RANKING =================
print("--- [PASSO 4] Gerando Listas de Vendas Ordenadas ---")

# Ordenação Mestra: 1º Ranking Potencial (Diamante...), 2º Qtd Parceiros Bairro
df_final = df_final.sort_values(by=['ranking_potencial', 'qtde_parceiros_bairro'], ascending=[True, False])

# 1. Ranking de Bairros para Planejamento
ranking_bairros = df_final.groupby('bairro_corrigido').agg(
    total_leads=('cnpj_basico', 'count'),
    media_parceiros=('qtde_parceiros_bairro', 'mean')
).reset_index().round(2).sort_values(by='media_parceiros', ascending=False)
ranking_bairros.to_csv(os.path.join(PASTA_SAIDA, f"00_MAPA_CALOR_BAIRROS.csv"), 
                       sep=';', index=False, encoding='utf-8-sig')

# 2. Arquivo Consolidado da Cidade
df_final[COLUNAS_VENDEDOR].to_csv(os.path.join(PASTA_SAIDA, f"00_CONSOLIDADO_GERAL_{CONFIG['CIDADE'].upper()}.csv"), 
                                 sep=';', index=False, encoding='utf-8-sig')

# 3. Arquivos Individuais por Bairro
for bairro in df_final['bairro_corrigido'].unique():
    df_b = df_final[df_final['bairro_corrigido'] == bairro].copy()
    bairro_seguro = limpar_nome_arquivo(bairro)
    nome_f = f"Leads_{bairro_seguro}.csv"
    
    df_b[COLUNAS_VENDEDOR].to_csv(os.path.join(PASTA_SAIDA, nome_f), 
                                  sep=';', index=False, encoding='utf-8-sig')

print(f"\n✅ SUCESSO! Pastas organizadas em: {CONFIG['UF']} > {CONFIG['CIDADE']}")