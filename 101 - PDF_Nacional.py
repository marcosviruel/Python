import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.backends.backend_pdf import PdfPages
import seaborn as sns
import os
import glob
import warnings
import logging
from datetime import datetime

# ================= 1. CONFIGURAÇÕES E AMBIENTE =================
warnings.filterwarnings("ignore")
logging.getLogger('matplotlib.font_manager').setLevel(logging.ERROR)

PASTA_BASE = r"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python\CSVs"
PASTA_ENTRADA = os.path.join(PASTA_BASE, "4_Leads_Comerciais_Estado")
PASTA_SAIDA = os.path.join(PASTA_BASE, "6_Relatorios_Estrategicos")
ARQUIVO_REDE = os.path.join(PASTA_BASE, "Rede_Credenciada_Supermercado.csv")

os.makedirs(PASTA_SAIDA, exist_ok=True)

# Identidade Visual Brasil Convênios
COR_PRIMARIA = "#173963"   # Azul Escuro
COR_SECUNDARIA = "#4EA6A6" # Verde Água
COR_TERCIARIA = "#509CBA"  # Azul Médio
COR_DESTAQUE = "#C0392B"   # Vermelho

MES_ANO = "FEV-26" # Ajustado conforme seu padrão

MAPA_REGIOES = {
    'AC': 'NORTE', 'AM': 'NORTE', 'AP': 'NORTE', 'PA': 'NORTE', 'RO': 'NORTE', 'RR': 'NORTE', 'TO': 'NORTE',
    'AL': 'NORDESTE', 'BA': 'NORDESTE', 'CE': 'NORDESTE', 'MA': 'NORDESTE', 'PB': 'NORDESTE', 'PE': 'NORDESTE', 'PI': 'NORDESTE', 'RN': 'NORDESTE', 'SE': 'NORDESTE',
    'DF': 'CENTRO-OESTE', 'GO': 'CENTRO-OESTE', 'MT': 'CENTRO-OESTE', 'MS': 'CENTRO-OESTE',
    'ES': 'SUDESTE', 'MG': 'SUDESTE', 'RJ': 'SUDESTE', 'SP': 'SUDESTE',
    'PR': 'SUL', 'RS': 'SUL', 'SC': 'SUL'
}

def fmt_br(x): 
    return f"{int(x):,}".replace(",", ".")

# ================= 2. PROCESSAMENTO NACIONAL (PASSO 1) =================
print(f"\n--- [1/3] Processando Base Nacional (Filtros MEI/2135) ---")

arquivos_estados = glob.glob(os.path.join(PASTA_ENTRADA, "Leads_Comercial_*.csv"))
if not arquivos_estados:
    print(f"ERRO: Nenhum arquivo encontrado em {PASTA_ENTRADA}"); exit()

lista_contagem = []

for arquivo in arquivos_estados:
    uf = os.path.basename(arquivo).split('_')[-1].replace('.csv', '').upper()
    try:
        # Leitura performática: apenas colunas necessárias
        df_chunk = pd.read_csv(arquivo, sep=';', dtype=str, usecols=['cnpj_basico', 'nome_municipio_real', 'natureza_juridica'])
        df_chunk.columns = [c.lower().strip() for c in df_chunk.columns]
        
        # Filtro de Qualidade: Remove MEI e Natureza Jurídica 2135
        df_chunk = df_chunk[~df_chunk['natureza_juridica'].str.contains('2135|MEI', case=False, na=False)]
        
        contagem = df_chunk.groupby('nome_municipio_real')['cnpj_basico'].nunique().reset_index()
        contagem.columns = ['municipio', 'leads_reais']
        contagem['uf'] = uf
        contagem['regiao'] = MAPA_REGIOES.get(uf, "OUTROS")
        lista_contagem.append(contagem)
        print(f" > {uf}: Processado.")
    except Exception as e:
        print(f" > Erro ao processar {uf}: {e}")

df_nacional = pd.concat(lista_contagem, ignore_index=True).sort_values(by='leads_reais', ascending=False)

# ================= 3. ANÁLISE DE REDE E KPI (PASSO 2) =================
print(f"--- [2/3] Cruzando Dados com Rede Credenciada ---")

# Processamento da Rede Credenciada
df_rede_bruta = pd.read_csv(ARQUIVO_REDE, sep=';', encoding='latin-1', dtype=str)
df_rede_bruta.columns = [c.upper() for c in df_rede_bruta.columns]
contagem_rede = df_rede_bruta.groupby('UF')['CODIGO'].nunique().reset_index()
contagem_rede.columns = ['uf', 'qtd_parceiros_real']

# Consolidação por UF
df_uf = df_nacional.groupby('uf').agg({'leads_reais': 'sum', 'regiao': 'first'}).reset_index()
df_uf = pd.merge(df_uf, contagem_rede, on='uf', how='left').fillna(0).sort_values('leads_reais', ascending=False)

# Métricas Globais
total_leads = df_nacional['leads_reais'].sum()
total_municipios = df_nacional['municipio'].nunique()
total_rede = contagem_rede['qtd_parceiros_real'].sum()

# ================= 4. GERAÇÃO DO DASHBOARD PDF (PASSO 3) =================
print(f"--- [3/3] Gerando Relatório Visual Executivo ---")

caminho_pdf = os.path.join(PASTA_SAIDA, f"Relatorio_Nacional_Brasil_Convenios_{MES_ANO}.pdf")

with PdfPages(caminho_pdf) as pdf:
    # --- PÁGINA 1: DASHBOARD ---
    fig1 = plt.figure(figsize=(24, 14))
    gs = gridspec.GridSpec(2, 2, figure=fig1, width_ratios=[1.3, 0.9], height_ratios=[1, 1])
    fig1.suptitle(f'ANÁLISE ESTRATÉGICA NACIONAL - BRASIL CONVÊNIOS ({MES_ANO})', 
                  fontsize=32, fontweight='bold', color=COR_PRIMARIA, y=0.97)

    # Q1: Gráfico de Pizza (Regiões)
    ax1 = fig1.add_subplot(gs[0, 0])
    resumo_reg = df_nacional.groupby('regiao')['leads_reais'].sum().sort_values(ascending=False)
    ax1.pie(resumo_reg, labels=resumo_reg.index, autopct='%1.1f%%', startangle=140, 
            colors=sns.color_palette("Blues_r", 5), pctdistance=0.75, 
            textprops={'fontsize': 12, 'fontweight': 'bold'})
    ax1.set_title('CONCENTRAÇÃO DE LEADS POR REGIÃO', fontsize=20, fontweight='bold', color=COR_PRIMARIA, pad=20)

    # Q2: Misto UF (Leads vs Rede) com Rótulos de Dados
    ax2 = fig1.add_subplot(gs[1, 0]); ax2_twin = ax2.twinx()
    sns.barplot(x='uf', y='leads_reais', data=df_uf, ax=ax2, palette="Blues_r", hue='uf', legend=False, alpha=0.9)
    
    # Rótulos das Barras (Leads)
    for i, v in enumerate(df_uf['leads_reais']):
        ax2.text(i, v + (df_uf['leads_reais'].max() * 0.01), fmt_br(v), 
                 ha='center', va='bottom', fontsize=9, color=COR_PRIMARIA, fontweight='bold')

    # Linha da Rede Credenciada
    ax2_twin.plot(df_uf['uf'], df_uf['qtd_parceiros_real'], marker='o', color=COR_DESTAQUE, linewidth=3, label='Rede Atual')
    
    # Rótulos da Linha (Rede) com BBox para destaque
    for i, v in enumerate(df_uf['qtd_parceiros_real']):
        ax2_twin.text(i, v + (df_uf['qtd_parceiros_real'].max() * 0.05), fmt_br(v), 
                      ha='center', va='bottom', fontsize=10, color='white', fontweight='bold',
                      bbox=dict(boxstyle='round,pad=0.3', fc=COR_DESTAQUE, ec='none'))
    
    ax2.set_title('COMPARATIVO: POTENCIAL (LEADS) VS PRESENÇA (REDE)', fontsize=18, fontweight='bold', color=COR_PRIMARIA)
    ax2.set_xticklabels(df_uf['uf'], fontweight='bold', fontsize=11)
    ax2_twin.set_ylim(0, df_uf['qtd_parceiros_real'].max() * 1.5) # Margem para rótulos

    # Q3: Ranking Top Municípios
    ax3 = fig1.add_subplot(gs[:, 1])
    top_30 = df_nacional.head(30).copy()
    sns.barplot(x='leads_reais', y='municipio', data=top_30, ax=ax3, palette="mako", hue='municipio', legend=False)
    for i, v in enumerate(top_30['leads_reais']):
        ax3.text(v + (top_30['leads_reais'].max() * 0.01), i, fmt_br(v), color=COR_PRIMARIA, va='center', fontweight='bold', fontsize=10)
    ax3.set_title('TOP 30 MUNICÍPIOS (ROI IMEDIATO)', fontsize=20, fontweight='bold', color=COR_PRIMARIA)

    plt.tight_layout(rect=[0.05, 0.05, 0.95, 0.93]); pdf.savefig(fig1); plt.close()

    # --- PÁGINA 2: SUMÁRIO EXECUTIVO ---
    fig2 = plt.figure(figsize=(24, 14)); ax_sum = fig2.add_subplot(111); ax_sum.axis('off')
    fig2.patch.set_facecolor('#F8F9F9')
    
    ax_sum.text(0.05, 0.92, f"SUMÁRIO EXECUTIVO: INTELIGÊNCIA DE MERCADO", fontsize=30, fontweight='bold', color=COR_PRIMARIA)
    ax_sum.axhline(y=0.89, xmin=0.05, xmax=0.95, color=COR_PRIMARIA, linewidth=2)

    # Cards de Métricas (KPIs)
    kpis = [("MUNICÍPIOS ANALISADOS", total_municipios, 0.05, COR_PRIMARIA), 
            ("POTENCIAL TOTAL (LEADS)", total_leads, 0.35, COR_TERCIARIA), 
            ("REDE CREDENCIADA ATUAL", total_rede, 0.65, COR_DESTAQUE)]
    
    for label, valor, x, cor in kpis:
        ax_sum.add_patch(plt.Rectangle((x, 0.70), 0.25, 0.12, color='white', ec=cor, lw=2))
        ax_sum.text(x+0.02, 0.78, label, fontsize=14, color='gray', fontweight='bold')
        ax_sum.text(x+0.02, 0.73, fmt_br(valor), fontsize=28, fontweight='bold', color=cor)

    # Texto de Metodologia e Insights
    metodologia = (
        "• Processamento: Integração de bases governamentais filtrando apenas empresas ativas.\n"
        "• Filtro de Qualidade: Exclusão de MEIs e Natureza Jurídica 2135 (Foco em Médio/Grande porte).\n"
        "• Regra de Cruzamento: Identificação de GAPs onde o potencial é alto e a rede é insuficiente.\n"
        "• Atualização: Dados consolidados referentes ao ciclo de " + MES_ANO + "."
    )
    ax_sum.text(0.05, 0.60, "NOTAS METODOLÓGICAS", fontsize=22, fontweight='bold', color=COR_PRIMARIA)
    ax_sum.text(0.05, 0.42, metodologia, fontsize=18, color='#333333', linespacing=2)

    insights = (
        "1. ESTRATÉGIA NACIONAL: Focar expansão nos estados com maior diferencial entre barras e linha.\n"
        "2. PRIORIDADE SUL/SUDESTE: Regiões que apresentam o maior volume bruto de leads qualificados.\n"
        "3. AÇÃO COMERCIAL: Utilizar o ranking Top 30 para prospecção de parceiros âncoras locais."
    )
    ax_sum.text(0.05, 0.32, "DIRETRIZES PARA A DIRETORIA", fontsize=22, fontweight='bold', color=COR_SECUNDARIA)
    ax_sum.text(0.05, 0.15, insights, fontsize=18, color='#333333', linespacing=2, 
                bbox=dict(facecolor='#E8F6F3', edgecolor='none', boxstyle='round,pad=1'))

    pdf.savefig(fig2); plt.close()

# Exportação Final dos Dados de Apoio
df_nacional.head(50).to_csv(os.path.join(PASTA_SAIDA, "RANKING_TOP_50_NACIONAL.csv"), sep=';', index=False, encoding='utf-8-sig')

print(f"\n{'='*60}")
print(f"✅ RELATÓRIO NACIONAL CONCLUÍDO!")
print(f"Arquivo: {caminho_pdf}")
print(f"{'='*60}")

os.startfile(caminho_pdf)