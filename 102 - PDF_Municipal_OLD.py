import pandas as pd
import matplotlib.pyplot as plt
import os
import geopandas as gpd
import seaborn as sns
import numpy as np
import unicodedata
from matplotlib.backends.backend_pdf import PdfPages

# 1. Função de Normalização
def normalizar(texto):
    if not texto: return ""
    texto = str(texto).upper().strip()
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    return texto

# ================= CONFIGURAÇÕES =================
CIDADE = "CURITIBA"
ESTADO = "PR"
PASTA_MAPA = r"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python\Códigos\MAPA_IPPUC"
PASTA_DADOS = rf"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python\CSVs\5_Segmenta_Cidade_Bairro\{ESTADO}\{CIDADE}"
ARQUIVO_CSV = os.path.join(PASTA_DADOS, f"00_CONSOLIDADO_{CIDADE}.csv")
CAMINHO_PDF = os.path.join(PASTA_DADOS, f"Mapa_Estrategico_{CIDADE}.pdf")
COR_BASE = "#173963" 

print(f"--- Reordenando Páginas e Finalizando Relatório: {CIDADE} ---")

try:
    # 2. CARREGAR DADOS
    df = pd.read_csv(ARQUIVO_CSV, sep=';', encoding='utf-8-sig', low_memory=False)
    df_bairros = df.groupby('bairro_corrigido').size().reset_index(name='total_leads')
    df_bairros['match_key'] = df_bairros['bairro_corrigido'].apply(normalizar)

    # 3. CARREGAR MAPA
    arquivos_shp = [f for f in os.listdir(PASTA_MAPA) if f.lower().endswith('.shp')]
    mapa_ippuc = gpd.read_file(os.path.join(PASTA_MAPA, arquivos_shp[0]))
    col_nome_mapa = 'NOME' if 'NOME' in mapa_ippuc.columns else mapa_ippuc.columns[0]
    mapa_ippuc['match_key_mapa'] = mapa_ippuc[col_nome_mapa].apply(normalizar)

    # 4. MATCH REFINADO
    traducao_nomes = {}
    chaves_csv = df_bairros['match_key'].unique()
    for n_mapa in mapa_ippuc['match_key_mapa'].unique():
        if n_mapa in chaves_csv:
            traducao_nomes[n_mapa] = n_mapa
        else:
            for n_csv in chaves_csv:
                if n_csv == "CENTRO": continue
                if n_csv in n_mapa or n_mapa in n_csv:
                    traducao_nomes[n_mapa] = n_csv
    mapa_ippuc['match_final'] = mapa_ippuc['match_key_mapa'].map(traducao_nomes)
    
    # 5. UNIÃO E RANKING
    mapa_final = mapa_ippuc.merge(df_bairros, left_on='match_final', right_on='match_key', how='left')
    mapa_final['total_leads'] = mapa_final['total_leads'].fillna(0)
    df_ativos = df_bairros[df_bairros['total_leads'] > 0].sort_values(by='total_leads', ascending=False).copy()
    df_ativos['ID_MAPA'] = range(1, len(df_ativos) + 1)
    mapa_plot = mapa_final.merge(df_ativos[['match_key', 'ID_MAPA']], on='match_key', how='left')

    # 6. PDF DE 4 PÁGINAS (ORDEM SOLICITADA)
    with PdfPages(CAMINHO_PDF) as pdf:
        
        # --- PÁGINA 1: RANKING ---
        fig1, ax1 = plt.subplots(figsize=(12, 8))
        top_20 = df_ativos.head(20)
        sns.barplot(data=top_20, x='total_leads', y='bairro_corrigido', palette="mako", ax=ax1)
        ax1.set_title(f"RANKING DE OPORTUNIDADES - {CIDADE}", fontsize=16, fontweight='bold', color=COR_BASE)
        for i, v in enumerate(top_20['total_leads']):
            ax1.text(v + 0.1, i, f" {int(v)}", va='center', fontweight='bold', color=COR_BASE)
        plt.tight_layout()
        pdf.savefig(fig1)
        plt.close()

        # --- PÁGINA 2: MAPA CALOR (VERMELHO - TÁTICO) ---
        fig2, ax2 = plt.subplots(figsize=(12, 12))
        mapa_plot.plot(column='total_leads', cmap='Reds', edgecolor='black', linewidth=0.3, legend=True, ax=ax2)
        for mk, gp in mapa_plot.dropna(subset=['ID_MAPA']).groupby('match_key'):
            centro = gp.geometry.unary_union.centroid
            ax2.text(centro.x, centro.y, str(int(gp['ID_MAPA'].iloc[0])), fontsize=9, fontweight='bold', ha='center', va='center', zorder=10,
                     bbox=dict(facecolor='white', alpha=0.8, edgecolor='none', boxstyle='round,pad=0.1'))
        ax2.set_title(f"MAPA DE CALOR: TRADICIONAL (CALOR) - {CIDADE}", fontsize=18, fontweight='bold', color=COR_BASE)
        ax2.axis('off')
        pdf.savefig(fig2)
        plt.close()

        # --- PÁGINA 3: MAPA (PADRÃO EMPRESA - CORES INVERTIDAS) ---
        fig4, ax4 = plt.subplots(figsize=(12, 12))
        mapa_plot.plot(column='total_leads', cmap='mako_r', edgecolor='#FFFFFF', linewidth=0.5, legend=True, 
                        legend_kwds={'label': "Volume de Leads", 'orientation': "horizontal", 'pad': 0.02}, ax=ax4)
        for mk, gp in mapa_plot.dropna(subset=['ID_MAPA']).groupby('match_key'):
            centro = gp.geometry.unary_union.centroid
            ax4.text(centro.x, centro.y, str(int(gp['ID_MAPA'].iloc[0])), fontsize=9, fontweight='bold', ha='center', va='center', zorder=10,
                     bbox=dict(facecolor='white', alpha=0.8, edgecolor='none', boxstyle='round,pad=0.1'))
        ax4.set_title(f"MAPA: IDENTIDADE BRASIL CONVÊNIOS - {CIDADE}", fontsize=18, fontweight='bold', color=COR_BASE)
        ax4.axis('off')
        plt.tight_layout()
        pdf.savefig(fig4)
        plt.close()

        # --- PÁGINA 4: LEGENDA TÉCNICA (FINAL) ---
        fig3, ax3 = plt.subplots(figsize=(12, 16)); ax3.axis('off')
        ax3.set_title(f"LEGENDA DE REFERÊNCIA - {CIDADE}", fontsize=16, fontweight='bold', color=COR_BASE, pad=40)
        n_col, n_lin = 3, int(np.ceil(len(df_ativos) / 3))
        x_pos = [0.02, 0.35, 0.68]
        for i, (idx, row) in enumerate(df_ativos.iterrows()):
            c, l = i // n_lin, i % n_lin
            # Ex: "01. CENTRO (540)"
            texto = f"{int(row['ID_MAPA']):02d}. {row['bairro_corrigido'][:18]} ({int(row['total_leads'])})"
            ax3.text(x_pos[c], 0.92 - (l * 0.022), texto, fontsize=9, family='monospace', va='top')
        
        # Cabeçalhos das colunas
        for x in x_pos:
            ax3.text(x, 0.94, "ID. BAIRRO (LEADS)", fontsize=10, fontweight='bold', color=COR_BASE)
            
        pdf.savefig(fig3)
        plt.close()

    print(f"✅ Relatório Final de 4 páginas gerado com a nova ordem!")
    os.startfile(CAMINHO_PDF)

except Exception as e:
    print(f"\n[!] ERRO: {e}")