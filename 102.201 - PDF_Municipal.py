import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import os
import geopandas as gpd
import seaborn as sns
import numpy as np
import unicodedata
import json
import re
import textwrap
from rapidfuzz import process
from matplotlib.backends.backend_pdf import PdfPages

# ================= 1. FUNÇÕES DE APOIO =================
def limpar_texto_universal(txt):
    if pd.isna(txt): return ""
    txt = unicodedata.normalize('NFKD', str(txt)).encode('ASCII', 'ignore').decode('ASCII')
    return re.sub(r'[^A-Z0-9\s]', '', txt.upper()).strip()

def fmt_br(x): 
    try: return f"{int(float(x)):,}".replace(",", ".")
    except: return "0"

# ================= 2. CONFIGURAÇÕES =================
PASTA_RAIZ = r"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python"
try:
    with open(os.path.join(os.path.dirname(__file__), "config.json"), 'r', encoding='utf-8') as f:
        CONFIG = json.load(f)
except:
    CONFIG = {"CIDADE": "CURITIBA", "UF": "PR"}

CIDADE_ALVO = CONFIG.get('CIDADE', 'CURITIBA').upper()
UF_ALVO = CONFIG.get('UF', 'PR').upper()
ARQUIVO_ESTADO = os.path.join(PASTA_RAIZ, "CSVs", "4_Leads_Comerciais_Estado", f"Leads_Comercial_{UF_ALVO}.csv")
PASTA_SAIDA = os.path.join(PASTA_RAIZ, "CSVs", "5_Segmenta_Cidade_Bairro", UF_ALVO, CIDADE_ALVO)
PASTA_MAPAS = os.path.join(PASTA_RAIZ, "MAPAS")

COR_PRIMARIA = "#173963"
PALETA_RANKING = {"1 - DIAMANTE - Campeao": "#0E243E", "2 - OURO - Prioridade Alta": "#2E5984", 
                  "3 - PRATA - Bom Potencial": "#509CBA", "4 - BRONZE - Menor Potencial": "#AED6F1"}

os.makedirs(PASTA_SAIDA, exist_ok=True)

# ================= 3. PROCESSAMENTO =================
print(f"--- [1/2] Processando {CIDADE_ALVO} ---")

try:
    pasta_cidade = next((os.path.join(PASTA_MAPAS, d) for d in os.listdir(PASTA_MAPAS) if CIDADE_ALVO in d.upper()), None)
    shp_path = os.path.join(pasta_cidade, next(f for f in os.listdir(pasta_cidade) if f.endswith('.shp')))
    mapa_geo = gpd.read_file(shp_path)
    col_b_mapa = next((c for c in mapa_geo.columns if any(p in c.upper() for p in ['BAIRRO', 'NOME', 'NM'])), mapa_geo.columns[0])
    bairros_oficiais = mapa_geo[col_b_mapa].apply(limpar_texto_universal).unique().tolist()

    chunks = pd.read_csv(ARQUIVO_ESTADO, sep=';', dtype=str, chunksize=100000)
    blocos = []
    cidade_limpa = limpar_texto_universal(CIDADE_ALVO)

    for chunk in chunks:
        chunk.columns = [c.lower().strip() for c in chunk.columns]
        col_cid = next((c for c in ['municipio', 'nome_municipio_real'] if c in chunk.columns), None)
        col_nat = next((c for c in ['natureza_juridica', 'cod_natureza_juridica'] if c in chunk.columns), None)
        col_rank = next((c for c in ['ranking_potencial', 'rank'] if c in chunk.columns), 'ranking_potencial')
        col_bairro_csv = next((c for c in ['bairro', 'nm_bairro'] if c in chunk.columns), 'bairro')

        if col_cid:
            df_t = chunk[chunk[col_cid].apply(limpar_texto_universal) == cidade_limpa].copy()
            if not df_t.empty:
                if col_nat: df_t = df_t[~df_t[col_nat].str.contains('2135|MEI', case=False, na=False)]
                df_t = df_t.rename(columns={col_rank: 'ranking_potencial', col_bairro_csv: 'bairro'})
                blocos.append(df_t)

    df_raw = pd.concat(blocos, ignore_index=True).drop_duplicates(subset=['cnpj_basico'])
    def ajustar_bairro(nome):
        res = process.extractOne(limpar_texto_universal(nome), bairros_oficiais, score_cutoff=70)
        return res[0] if res else "OUTROS"

    df_raw['bairro_corrigido'] = df_raw['bairro'].apply(ajustar_bairro)
    df_final = df_raw[df_raw['bairro_corrigido'] != "OUTROS"].copy()

    df_geral = df_final.groupby('bairro_corrigido').size().reset_index(name='total_leads').sort_values('total_leads', ascending=False).reset_index(drop=True)
    df_geral['ID_CALOR'] = range(1, len(df_geral) + 1)
    
    df_diam = df_final[df_final['ranking_potencial'].str.contains("DIAMANTE", na=False)].groupby('bairro_corrigido').size().reset_index(name='qtd_diamantes').sort_values('qtd_diamantes', ascending=False).reset_index(drop=True)
    df_diam['ID_DIAMANTE'] = range(1, len(df_diam) + 1)

except Exception as e:
    print(f"Erro: {e}"); exit()

# ================= 4. GERAÇÃO DO PDF =================
caminho_pdf = os.path.join(PASTA_SAIDA, f"Relatorio_Estrategico_{CIDADE_ALVO}.pdf")

with PdfPages(caminho_pdf) as pdf:
    # PÁGINA 1: DASHBOARD
    fig1 = plt.figure(figsize=(24, 14))
    gs = gridspec.GridSpec(1, 2, figure=fig1)
    fig1.suptitle(f'INTELIGÊNCIA COMERCIAL: {CIDADE_ALVO}', fontsize=32, fontweight='bold', color=COR_PRIMARIA)
    ax_p = fig1.add_subplot(gs[0, 0])
    res_rank = df_final['ranking_potencial'].value_counts().sort_index()
    patches, texts, autotexts = ax_p.pie(res_rank, labels=[l.split('-')[1].strip() if '-' in l else l for l in res_rank.index], autopct='%1.1f%%', colors=list(PALETA_RANKING.values()), startangle=140)
    for i, a_text in enumerate(autotexts):
        a_text.set_fontweight('bold')
        if "DIAMANTE" in res_rank.index[i]: a_text.set_color('white')
    ax_p.set_title("CLASSIFICAÇÃO DE LEADS", fontsize=22, fontweight='bold')
    ax_b = fig1.add_subplot(gs[0, 1])
    bars = sns.barplot(data=df_geral.head(25), x='total_leads', y='bairro_corrigido', palette="mako", ax=ax_b)
    for p in bars.patches:
        ax_b.annotate(fmt_br(p.get_width()), (p.get_width(), p.get_y() + p.get_height()/2.), ha='left', va='center', fontsize=11, fontweight='bold', xytext=(5,0), textcoords='offset points')
    ax_b.set_title("TOP 25 BAIRROS (VOLUME)", fontsize=20, fontweight='bold')
    plt.tight_layout(rect=[0.05, 0.05, 0.95, 0.93]); pdf.savefig(fig1); plt.close()

    # PÁGINA 2: METODOLOGIA E DEFINIÇÕES ESTRATÉGICAS
    fig_g = plt.figure(figsize=(24, 14)); ax_g = fig_g.add_subplot(111); ax_g.axis('off')
    fig_g.patch.set_facecolor('#F8F9F9')
    ax_g.text(0.5, 0.94, "METODOLOGIA E DEFINIÇÕES ESTRATÉGICAS", fontsize=28, fontweight='bold', color=COR_PRIMARIA, ha='center')
    ax_g.axhline(y=0.91, xmin=0.1, xmax=0.9, color=COR_PRIMARIA, linewidth=2)

    def add_topico(eixo, x, y, tit, txt):
        eixo.text(x, y, tit, fontsize=18, fontweight='bold', color=COR_PRIMARIA)
        wrap = "\n".join(textwrap.wrap(txt, 115))
        eixo.text(x, y-0.03, wrap, fontsize=15, color='#333333', linespacing=1.5, va='top')
        return y - 0.20

    y_pos = 0.85
    y_pos = add_topico(ax_g, 0.1, y_pos, "1. CLASSIFICAÇÃO DIAMANTE (POTENCIAL MÁXIMO)", "Representa empresas com Capital Social superior a R$ 1.000.000,00 ou faturamento estimado de grande porte. São os leads com maior robustez financeira e solidez patrimonial.")
    y_pos = add_topico(ax_g, 0.1, y_pos, "2. FILTRO DE NATUREZA JURÍDICA", "Para garantir a eficácia comercial, foram removidos da base: MEIs (Microempreendedores Individuais), Órgãos da Administração Pública, Entidades Sem Fins Lucrativos e Associações.")
    y_pos = add_topico(ax_g, 0.1, y_pos, "3. LÓGICA DE CAPITAL SOCIAL E RANKING", "O Capital Social é indicador de solvência. DIAMANTES possuem capital acima de R$ 1.000.000; OUROS e PRATAS possuem capital entre R$ 100.000 e R$ 1.000.000; BRONZES possuem capital abaixo de R$ 100.000.")
    y_pos = add_topico(ax_g, 0.1, y_pos, "4. HIGIENE DE DADOS E GEOPROCESSAMENTO", "A base foi cruzada com a malha oficial de bairros (Gabarito IPPUC/SHP). Erros de digitação foram corrigidos via Inteligência Artificial (Fuzzy Match) para garantir precisão geográfica em " + CIDADE_ALVO + ".")
    ax_g.text(0.5, 0.08, "Relatório Gerado para Brasil Convênios - Inteligência de Dados", fontsize=12, style='italic', color='#999999', ha='center')
    pdf.savefig(fig_g); plt.close()

    # MAPAS E LEGENDAS (PÁGINAS 3 A 6)
    mapa_geo['match_key'] = mapa_geo[col_b_mapa].apply(limpar_texto_universal)
    config_paginas = [
        ('CALOR', df_geral, 'YlOrRd', 'ID_CALOR', 'total_leads', 'black', 'white'),
        ('DIAMANTES', df_diam, 'Blues', 'ID_DIAMANTE', 'qtd_diamantes', 'white', '#0E243E')
    ]

    for titulo, df_uso, mapa_cor, id_col, val_col, txt_cor, bg_cor in config_paginas:
        fig, ax = plt.subplots(figsize=(15, 15))
        m = mapa_geo.merge(df_uso, left_on='match_key', right_on='bairro_corrigido', how='left')
        m.plot(column=val_col, cmap=mapa_cor, edgecolor='black', linewidth=0.4, ax=ax, legend=True, missing_kwds={'color': '#f2f2f2'})
        for _, r in m.dropna(subset=[id_col]).iterrows():
            jx, jy = np.random.uniform(-0.0007, 0.0007, 2)
            ax.text(r.geometry.centroid.x + jx, r.geometry.centroid.y + jy, str(int(r[id_col])), fontsize=8, fontweight='bold', ha='center', color=txt_cor, bbox=dict(facecolor=bg_cor, alpha=0.7, edgecolor='none', pad=1))
        ax.set_title(f"MAPA DE {titulo} - {CIDADE_ALVO}", fontsize=22, fontweight='bold'); ax.axis('off'); pdf.savefig(fig); plt.close()
        
        fig_l, ax_l = plt.subplots(figsize=(24, 14)); ax_l.axis('off')
        ax_l.set_title(f"LEGENDA BAIRROS ({titulo}) - {CIDADE_ALVO}", fontsize=22, fontweight='bold', color=COR_PRIMARIA, pad=30)
        cx = [0.05, 0.38, 0.71]
        df_ord = df_uso.sort_values(id_col).reset_index(drop=True)
        for i, r in df_ord.iterrows():
            col, row = (i // 25), (i % 25)
            if col < 3:
                ax_l.text(cx[col], 0.90 - (row * 0.032), f"{int(r[id_col]):02d}. {r['bairro_corrigido'][:25]} ({int(r[val_col])})", fontsize=11, family='monospace', fontweight='bold' if titulo=='DIAMANTES' else 'normal')
        pdf.savefig(fig_l); plt.close()

print(f"✅ Relatório Finalizado com Sucesso!")
os.startfile(caminho_pdf)