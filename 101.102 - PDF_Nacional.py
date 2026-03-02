import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.backends.backend_pdf import PdfPages
import seaborn as sns
import os
import glob
import warnings
import textwrap

# ================= 1. CONFIGURAÇÕES E AMBIENTE =================
warnings.filterwarnings("ignore")
PASTA_BASE = r"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python\CSVs"
PASTA_ENTRADA = os.path.join(PASTA_BASE, "4_Leads_Comerciais_Estado")
PASTA_SAIDA = os.path.join(PASTA_BASE, "6_Relatorios_Estrategicos")
ARQUIVO_REDE = os.path.join(PASTA_BASE, "Rede_Credenciada_Supermercado.csv")

os.makedirs(PASTA_SAIDA, exist_ok=True)

COR_PRIMARIA = "#173963"   
COR_DESTAQUE = "#C0392B" # Vermelho estratégico para a Rede
PALETA_RANKING = {"1 - DIAMANTE - Campeao": "#0E243E", "2 - OURO - Prioridade Alta": "#2E5984", 
                  "3 - PRATA - Bom Potencial": "#509CBA", "4 - BRONZE - Menor Potencial": "#AED6F1"}

MES_ANO = "FEV-26"

def fmt_br(x): 
    return f"{int(x):,}".replace(",", ".")

# ================= 2. PROCESSAMENTO =================
arquivos_estados = glob.glob(os.path.join(PASTA_ENTRADA, "Leads_Comercial_*.csv"))
lista_contagem = []

for arquivo in arquivos_estados:
    uf = os.path.basename(arquivo).split('_')[-1].replace('.csv', '').upper()
    try:
        df_st = pd.read_csv(arquivo, sep=';', dtype=str, usecols=['ranking_potencial', 'nome_municipio_real'])
        contagem = df_st.groupby(['nome_municipio_real', 'ranking_potencial']).size().reset_index(name='qtd')
        contagem['uf'] = uf
        lista_contagem.append(contagem)
    except: continue

df_nacional = pd.concat(lista_contagem, ignore_index=True)

df_rede_bruta = pd.read_csv(ARQUIVO_REDE, sep=';', encoding='latin-1', dtype=str)
df_rede_bruta.columns = [c.upper() for c in df_rede_bruta.columns]
contagem_rede = df_rede_bruta.groupby('UF')['CODIGO'].nunique().reset_index()
contagem_rede.columns = ['uf', 'qtd_parceiros_real']

df_uf_total = df_nacional.groupby('uf')['qtd'].sum().reset_index()
df_uf_total = pd.merge(df_uf_total, contagem_rede, on='uf', how='left').fillna(0).sort_values('qtd', ascending=False)

total_leads = df_nacional['qtd'].sum()
total_diamantes = df_nacional[df_nacional['ranking_potencial'].str.contains("DIAMANTE")]['qtd'].sum()
total_rede = contagem_rede['qtd_parceiros_real'].sum()

# ================= 3. GERAÇÃO DO PDF =================
caminho_pdf = os.path.join(PASTA_SAIDA, f"Relatorio_Nacional_Brasil_Convenios_{MES_ANO}.pdf")

with PdfPages(caminho_pdf) as pdf:
    
    # --- PÁGINA 1: DASHBOARD ---
    fig1 = plt.figure(figsize=(24, 14))
    gs = gridspec.GridSpec(2, 2, figure=fig1, width_ratios=[1.2, 1], height_ratios=[1, 1])
    fig1.suptitle(f'RELATÓRIO DE INTELIGÊNCIA COMERCIAL - BRASIL CONVÊNIOS ({MES_ANO})', fontsize=32, fontweight='bold', color=COR_PRIMARIA, y=0.97)

    ax1 = fig1.add_subplot(gs[0, 0])
    resumo_rank = df_nacional.groupby('ranking_potencial')['qtd'].sum()
    patches, texts, autotexts = ax1.pie(resumo_rank, labels=[l.split('-')[1].strip() for l in resumo_rank.index], autopct='%1.1f%%', colors=PALETA_RANKING.values(), startangle=140, pctdistance=0.85)
    for i, a_text in enumerate(autotexts):
        if "DIAMANTE" in resumo_rank.index[i]: a_text.set_color('white')
        a_text.set_fontweight('bold')
    ax1.set_title('QUALIDADE DA BASE (RANKING ESTRATÉGICO)', fontsize=20, fontweight='bold', color=COR_PRIMARIA)

    ax2 = fig1.add_subplot(gs[1, 0]); ax2_twin = ax2.twinx()
    bars = sns.barplot(x='uf', y='qtd', data=df_uf_total, ax=ax2, palette="Blues_r", hue='uf', legend=False)
    for p in bars.patches:
        ax2.annotate(fmt_br(p.get_height()), (p.get_x() + p.get_width() / 2., p.get_height()), ha='center', va='bottom', fontsize=9, fontweight='bold', color=COR_PRIMARIA, xytext=(0, 3), textcoords='offset points')
    ax2_twin.plot(df_uf_total['uf'], df_uf_total['qtd_parceiros_real'], marker='s', color=COR_DESTAQUE, linewidth=3)
    for i, txt in enumerate(df_uf_total['qtd_parceiros_real']):
        ax2_twin.annotate(fmt_br(txt), (df_uf_total['uf'].iloc[i], df_uf_total['qtd_parceiros_real'].iloc[i]), xytext=(0, 22), textcoords="offset points", ha='center', color='white', fontweight='bold', bbox=dict(boxstyle='round,pad=0.3', fc=COR_DESTAQUE, ec='none'))
    ax2.set_title('POTENCIAL LEADS POR UF VS N° CREDENCIADOS', fontsize=18, fontweight='bold', color=COR_PRIMARIA)
    ax2_twin.set_ylim(0, df_uf_total['qtd_parceiros_real'].max() * 1.5)

    ax3 = fig1.add_subplot(gs[:, 1])
    top_diamantes = df_nacional[df_nacional['ranking_potencial'].str.contains("DIAMANTE")].sort_values('qtd', ascending=False).head(25)
    bars_h = sns.barplot(x='qtd', y='nome_municipio_real', data=top_diamantes, ax=ax3, palette="mako", hue='nome_municipio_real', legend=False)
    for p in bars_h.patches:
        ax3.annotate(fmt_br(p.get_width()), (p.get_width(), p.get_y() + p.get_height() / 2.), ha='left', va='center', fontsize=10, fontweight='bold', color=COR_PRIMARIA, xytext=(5, 0), textcoords='offset points')
    ax3.set_title('TOP 25 CIDADES: FOCO EM DIAMANTES', fontsize=20, fontweight='bold', color=COR_PRIMARIA)

    plt.tight_layout(rect=[0.05, 0.05, 0.95, 0.93]); pdf.savefig(fig1); plt.close()

    # --- PÁGINA 2: METODOLOGIA ---
    fig2 = plt.figure(figsize=(24, 14)); ax_met = fig2.add_subplot(111); ax_met.axis('off')
    fig2.patch.set_facecolor('#F8F9F9')
    ax_met.text(0.05, 0.94, "FUNDAMENTOS DA QUALIFICAÇÃO E ANÁLISE PATRIMONIAL", fontsize=30, fontweight='bold', color=COR_PRIMARIA)
    ax_met.axhline(y=0.92, xmin=0.05, xmax=0.95, color=COR_PRIMARIA, linewidth=2)

    def desenhar_bloco(eixo, x, y, titulo, texto, largura=110):
        eixo.text(x, y, titulo, fontsize=20, fontweight='bold', color=COR_PRIMARIA)
        texto_wrap = "\n".join(textwrap.wrap(texto, largura))
        eixo.text(x, y - 0.03, texto_wrap, fontsize=18, color='#333333', linespacing=1.6, va='top')
        return y - 0.20

    y_pos = 0.85
    y_pos = desenhar_bloco(ax_met, 0.05, y_pos, "1. HIGIENE E FILTROS DE EXCLUSÃO:", "Esta análise foca exclusivamente em Sociedades Empresárias (Grupo 2 da Receita Federal). Empresas registradas como MEI (2135-2), Órgãos Públicos e Entidades sem fins lucrativos foram removidos para garantir que o potencial de leads reflita apenas o mercado corporativo privado.")
    y_pos = desenhar_bloco(ax_met, 0.05, y_pos, "2. RELEVÂNCIA DO PORTE 05 (DEMAIS):", "O Porte 05 identifica empresas com faturamento anual superior a R$ 4,8 milhões (fora do Simples Nacional). Estrategicamente, estas empresas possuem estruturas de RH mais robustas e maior volume de colaboradores, representando o público-alvo prioritário para a implementação de convênios de larga escala.")
    y_pos = desenhar_bloco(ax_met, 0.05, y_pos, "3. LÓGICA DO CAPITAL SOCIAL (ESTABILIDADE):", "Houve a decisão estratégica de classificar a base por Capital Social, estabelecendo os cortes de R$ 1.000.000 (Diamante) e R$ 100.000 (Prata). Esses valores funcionam como um indicador de solvência econômica, ou seja, demonstram a robustez patrimonial da empresa. Empresas com maior capitalização possuem maior resiliência financeira, garantindo que a Brasil Convênios atue com parceiros que apresentam baixo risco de descontinuidade operacional.")

    col_x = [0.05, 0.28, 0.51, 0.74]
    rank_info = [("DIAMANTE", "Elite Patrimonial\nPatrimônio > R$ 1MM", "#0E243E", "white"), ("OURO", "Grande Porte (05)\nFaturamento > R$ 4.8MM", "#2E5984", "white"), ("PRATA", "Médio Mercado (03)\nPatrimônio > R$ 100k", "#509CBA", "black"), ("BRONZE", "Foco em Volume\nCapilaridade Local", "#AED6F1", "black")]
    for i, (titulo, desc, cor, t_cor) in enumerate(rank_info):
        ax_met.add_patch(plt.Rectangle((col_x[i], 0.08), 0.21, 0.16, color=cor))
        ax_met.text(col_x[i]+0.01, 0.19, titulo, fontsize=20, fontweight='bold', color=t_cor)
        ax_met.text(col_x[i]+0.01, 0.11, desc, fontsize=14, color=t_cor, fontweight='bold')
    pdf.savefig(fig2); plt.close()

    # --- PÁGINA 3: SUMÁRIO E KPIS (ORDEM E CORES AJUSTADAS) ---
    fig3 = plt.figure(figsize=(24, 14)); ax_sum = fig3.add_subplot(111); ax_sum.axis('off')
    ax_sum.text(0.5, 0.90, "SUMÁRIO EXECUTIVO E INDICADORES (KPIs)", fontsize=30, fontweight='bold', color=COR_PRIMARIA, ha='center')
    
    largura_box = 0.26
    # Ordem alterada: Municípios (Esq), Rede Credenciada (Centro), Potencial Diamante (Dir)
    kpis = [
        ("MUNICÍPIOS ANALISADOS", df_nacional['nome_municipio_real'].nunique(), 0.06, COR_PRIMARIA), 
        ("REDE CREDENCIADA", total_rede, 0.37, COR_DESTAQUE), 
        ("POTENCIAL DIAMANTE", total_diamantes, 0.68, COR_PRIMARIA)
    ]
    
    for label, valor, x, cor_elemento in kpis:
        # Retângulo com a cor da borda condicional
        ax_sum.add_patch(plt.Rectangle((x, 0.65), largura_box, 0.15, color='white', ec=cor_elemento, lw=4))
        
        centro_x = x + (largura_box / 2)
        
        # Rótulo em Negrito e Preto
        ax_sum.text(centro_x, 0.76, label, fontsize=16, fontweight='bold', color='black', ha='center', va='center')
        
        # Valor com a cor condicional (Azul para Diamante/Municípios, Vermelho para Rede)
        ax_sum.text(centro_x, 0.70, fmt_br(valor), fontsize=32, fontweight='bold', color=cor_elemento, ha='center', va='center')

    pdf.savefig(fig3); plt.close()

print(f"--- [OK] Relatório Finalizado com Sucesso: {caminho_pdf} ---")
os.startfile(caminho_pdf)