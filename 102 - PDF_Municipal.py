import pandas as pd
import matplotlib.pyplot as plt
import os
import geopandas as gpd
import seaborn as sns
import numpy as np
import unicodedata
import json
import re
from rapidfuzz import process
from matplotlib.backends.backend_pdf import PdfPages

# ================= 1. FUNÇÕES DE APOIO (LÓGICA UNIVERSAL) =================
def limpar_texto_universal(txt):
    if pd.isna(txt): return ""
    txt = unicodedata.normalize('NFKD', str(txt)).encode('ASCII', 'ignore').decode('ASCII')
    return re.sub(r'[^A-Z0-9\s]', '', txt.upper()).strip()

def normalizar_para_mapa(texto):
    if not texto: return ""
    termos_remover = ['BAIRRO', 'DISTRITO', 'VILA', 'LOTEAMENTO', 'CONJUNTO', 'JARDIM', 'JD']
    texto = str(texto).upper().strip()
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    for termo in termos_remover:
        texto = re.sub(rf'\b{termo}\b', '', texto)
    return texto.strip()

def limpar_nome_arquivo(nome):
    return re.sub(r'[\\/*?:"<>|]', '', str(nome)).strip().replace(" ", "_")

# ================= 2. CONFIGURAÇÕES =================
DIRETORIO_DO_SCRIPT = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_CONFIG = os.path.join(DIRETORIO_DO_SCRIPT, "config.json")

with open(ARQUIVO_CONFIG, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

CIDADE_ALVO = CONFIG['CIDADE'].upper()
UF_ALVO = CONFIG['UF'].upper()
PASTA_RAIZ = r"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python"
ARQUIVO_ESTADO = os.path.join(PASTA_RAIZ, "CSVs", "4_Leads_Comerciais_Estado", f"Leads_Comercial_{UF_ALVO}.csv")
PASTA_SAIDA = os.path.join(PASTA_RAIZ, "CSVs", "5_Segmenta_Cidade_Bairro", UF_ALVO, CIDADE_ALVO)
PASTA_MAPAS = os.path.join(PASTA_RAIZ, "MAPAS")

os.makedirs(PASTA_SAIDA, exist_ok=True)

# ================= 3. PASSO 1: PROCESSAMENTO =================
print(f"\n--- [1/2] Lendo Dados: {CIDADE_ALVO} ---")

try:
    chunks = pd.read_csv(ARQUIVO_ESTADO, sep=';', dtype=str, chunksize=100000)
    blocos = []
    cidade_limpa = limpar_texto_universal(CIDADE_ALVO)

    for chunk in chunks:
        chunk.columns = [c.lower().strip() for c in chunk.columns]
        col_cid = next((c for c in ['municipio', 'nome_municipio_real', 'nm_municipio'] if c in chunk.columns), None)
        if col_cid:
            mask = chunk[col_cid].apply(limpar_texto_universal) == cidade_limpa
            df_t = chunk[mask].copy()
            if not df_t.empty:
                df_t = df_t[~df_t['natureza_juridica'].str.contains('2135|MEI', case=False, na=False)]
                blocos.append(df_t)

    df_base = pd.concat(blocos, ignore_index=True)
    df_base['bairro_limpo'] = df_base['bairro'].apply(limpar_texto_universal)
    
    gabarito = df_base['bairro_limpo'].value_counts().index.tolist()[:CONFIG.get('TOP_N_BAIRROS', 60)]
    df_base['bairro_corrigido'] = df_base['bairro_limpo'].apply(lambda x: (process.extractOne(x, gabarito, score_cutoff=75) or ("OUTROS",))[0])

    df_final = df_base.drop_duplicates(subset=['cnpj_basico']).copy()
    df_resumo = df_final.groupby('bairro_corrigido').size().reset_index(name='total_leads')
    df_resumo['match_key'] = df_resumo['bairro_corrigido'].apply(normalizar_para_mapa)
    df_ativos = df_resumo[df_resumo['total_leads'] > 0].sort_values(by='total_leads', ascending=False).copy()
    df_ativos['ID_MAPA'] = range(1, len(df_ativos) + 1)

    # Exportação dos CSVs por bairro
    for b in df_final['bairro_corrigido'].unique():
        df_final[df_final['bairro_corrigido'] == b].to_csv(os.path.join(PASTA_SAIDA, f"Leads_{CIDADE_ALVO}_{limpar_nome_arquivo(b)}.csv"), sep=';', index=False, encoding='utf-8-sig')

except Exception as e:
    print(f"Erro Dados: {e}"); exit()

# ================= 4. PASSO 2: PDF COM LEGENDA DINÂMICA =================
print(f"--- [2/2] Gerando Relatório Estratégico Completo ---")

try:
    tem_mapa, mapa_final = False, None
    pasta_cidade = next((os.path.join(PASTA_MAPAS, d) for d in os.listdir(PASTA_MAPAS) if CIDADE_ALVO in d.upper() and os.path.isdir(os.path.join(PASTA_MAPAS, d))), None)

    if pasta_cidade:
        shp_file = next((f for f in os.listdir(pasta_cidade) if f.lower().endswith('.shp')), None)
        if shp_file:
            mapa_geo = gpd.read_file(os.path.join(pasta_cidade, shp_file))
            colunas_texto = mapa_geo.select_dtypes(include=['object']).columns
            col_bairro = None
            palavras_alvo = ['BAIRRO', 'NOME', 'NM', 'DIST', 'SUB']
            for p in palavras_alvo:
                match = [c for c in colunas_texto if p in c.upper()]
                if match:
                    col_bairro = max(match, key=lambda c: mapa_geo[c].nunique())
                    break
            
            if col_bairro:
                mapa_geo['match_key_mapa'] = mapa_geo[col_bairro].apply(normalizar_para_mapa)
                def fuzzy_match_geo(val):
                    res = process.extractOne(val, df_ativos['match_key'].tolist(), score_cutoff=50)
                    return res[0] if res else None
                mapa_geo['match_key_mapa'] = mapa_geo['match_key_mapa'].apply(fuzzy_match_geo)
                mapa_final = mapa_geo.merge(df_ativos, left_on='match_key_mapa', right_on='match_key', how='left')
                mapa_final['total_leads'] = mapa_final['total_leads'].fillna(0)
                tem_mapa = True

    caminho_pdf = os.path.join(PASTA_SAIDA, f"Relatorio_Estrategico_{CIDADE_ALVO}.pdf")
    with PdfPages(caminho_pdf) as pdf:
        # PÁGINA 1: Ranking de Barras
        fig1, ax1 = plt.subplots(figsize=(12, 10))
        sns.barplot(data=df_ativos.head(40), x='total_leads', y='bairro_corrigido', hue='bairro_corrigido', palette="mako", legend=False, ax=ax1)
        for i, v in enumerate(df_ativos.head(40)['total_leads']):
            ax1.text(v + 1, i, str(int(v)), va='center', fontweight='bold', color='#173963')
        ax1.set_title(f"POTENCIAL COMERCIAL POR BAIRRO - {CIDADE_ALVO}", fontsize=16, fontweight='bold')
        plt.tight_layout(); pdf.savefig(fig1); plt.close()

        # PÁGINAS 2 e 3: Mapas (se houver)
        if tem_mapa:
            for cmap in ['YlOrRd', 'mako_r']:
                fig, ax = plt.subplots(figsize=(12, 12))
                mapa_final.plot(column='total_leads', cmap=cmap, edgecolor='black', linewidth=0.4, legend=True, ax=ax, missing_kwds={'color': '#f2f2f2'}, vmin=0.1)
                for _, r in mapa_final.dropna(subset=['ID_MAPA']).iterrows():
                    ax.text(r.geometry.centroid.x, r.geometry.centroid.y, str(int(r['ID_MAPA'])), fontsize=6, fontweight='bold', ha='center', bbox=dict(facecolor='white', alpha=0.4, edgecolor='none'))
                ax.set_title(f"MAPA DE CALOR/DENSIDADE - {CIDADE_ALVO}", fontsize=18, fontweight='bold')
                ax.axis('off'); pdf.savefig(fig, bbox_inches='tight'); plt.close()

        # PÁGINA 4+ : A LEGENDA DINÂMICA (RESTAURADA)
        # Quantidade de itens por página para não amontoar
        itens_por_pagina = 120 
        total_bairros = len(df_ativos)
        
        for inicio in range(0, total_bairros, itens_por_pagina):
            fig_leg, ax_leg = plt.subplots(figsize=(12, 16))
            ax_leg.axis('off')
            
            slice_bairros = df_ativos.iloc[inicio : inicio + itens_por_pagina]
            
            titulo_legenda = f"LEGENDA DE REFERÊNCIA - {CIDADE_ALVO}"
            if total_bairros > itens_por_pagina:
                titulo_legenda += f" (Parte {int(inicio/itens_por_pagina)+1})"
            
            ax_leg.set_title(titulo_legenda, fontsize=16, fontweight='bold', color='#173963', pad=20)
            
            # Divide a página em 3 colunas para a legenda
            colunas_x = [0.05, 0.38, 0.71]
            linhas_max = 40 # 40 linhas x 3 colunas = 120 itens
            
            for idx, (original_idx, row) in enumerate(slice_bairros.iterrows()):
                col_atual = idx // linhas_max
                lin_atual = idx % linhas_max
                
                texto_bairro = f"{int(row['ID_MAPA']):02d}. {row['bairro_corrigido'][:22]} ({int(row['total_leads'])})"
                ax_leg.text(colunas_x[col_atual], 0.95 - (lin_atual * 0.022), texto_bairro, 
                            fontsize=8, family='monospace', verticalalignment='top')
            
            pdf.savefig(fig_leg)
            plt.close()

    print(f"✅ Relatório Completo Gerado com Sucesso em: {PASTA_SAIDA}")
    os.startfile(caminho_pdf)

except Exception as e:
    print(f"Erro ao gerar Relatório: {e}")