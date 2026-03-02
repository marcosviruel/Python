import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.backends.backend_pdf import PdfPages
import seaborn as sns
import os
import glob
import warnings
import logging

# ================= 1. CONFIGURAÇÕES E AMBIENTE =================
warnings.filterwarnings("ignore")
logging.getLogger('matplotlib.font_manager').setLevel(logging.ERROR)

PASTA_BASE = r"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python\CSVs"
PASTA_ENTRADA = os.path.join(PASTA_BASE, "Rede_Farmacia_Com_CEP_Offline")
PASTA_SAIDA = os.path.join(PASTA_BASE, "6_Relatorios_Estrategicos_Farmacia")
ARQUIVO_REDE = os.path.join(PASTA_ENTRADA, "REDE_FARMACIAS_ENRIQUECIDA_FULL.csv")

os.makedirs(PASTA_SAIDA, exist_ok=True)

COR_PRIMARIA = "#173963"   # Azul Brasil Convênios
COR_SECUNDARIA = "#4EA6A6" # Verde Água
COR_TERCIARIA = "#509CBA"  # Azul Médio
COR_DESTAQUE = "#C0392B"   # Vermelho Alerta (GAPs)

MES_ANO = "FEV-26" 

MAPA_REGIOES = {
    'AC': 'NORTE', 'AM': 'NORTE', 'AP': 'NORTE', 'PA': 'NORTE', 'RO': 'NORTE', 'RR': 'NORTE', 'TO': 'NORTE',
    'AL': 'NORDESTE', 'BA': 'NORDESTE', 'CE': 'NORDESTE', 'MA': 'NORDESTE', 'PB': 'NORDESTE', 'PE': 'NORDESTE', 'PI': 'NORDESTE', 'RN': 'NORDESTE', 'SE': 'NORDESTE',
    'DF': 'CENTRO-OESTE', 'GO': 'CENTRO-OESTE', 'MT': 'CENTRO-OESTE', 'MS': 'CENTRO-OESTE',
    'ES': 'SUDESTE', 'MG': 'SUDESTE', 'RJ': 'SUDESTE', 'SP': 'SUDESTE',
    'PR': 'SUL', 'RS': 'SUL', 'SC': 'SUL'
}

def fmt_br(x): 
    return f"{int(x):,}".replace(",", ".")

# ================= 2. PROCESSAMENTO NACIONAL =================
print(f"\n--- [1/3] Processando Base Nacional de Leads (Setor Farmácia) ---")

arquivos_estados = glob.glob(os.path.join(PASTA_ENTRADA, "Leads_Comercial_*.csv"))
if not arquivos_estados:
    print(f"❌ ERRO: Nenhum arquivo encontrado em {PASTA_ENTRADA}"); exit()

lista_contagem = []
colunas_leitura = ['cnpj_basico', 'nome_municipio_real', 'natureza_juridica']

for arquivo in arquivos_estados:
    uf = os.path.basename(arquivo).split('_')[-1].replace('.csv', '').upper()
    try:
        df_chunk = pd.read_csv(arquivo, sep=';', dtype=str, usecols=colunas_leitura)
        df_chunk = df_chunk[~df_chunk['natureza_juridica'].str.contains('2135|MEI', case=False, na=False)]
        
        if not df_chunk.empty:
            contagem = df_chunk.groupby('nome_municipio_real')['cnpj_basico'].nunique().reset_index()
            contagem.columns = ['municipio', 'leads_reais']
            contagem['uf'] = uf
            contagem['regiao'] = MAPA_REGIOES.get(uf, "OUTROS")
            lista_contagem.append(contagem)
            print(f" > {uf}: {fmt_br(len(df_chunk))} leads processados.")
    except: pass

if not lista_contagem:
    print("❌ Erro: Lista de contagem vazia."); exit()

df_nacional = pd.concat(lista_contagem, ignore_index=True).sort_values(by='leads_reais', ascending=False)

# ================= 3. ANÁLISE DE REDE CREDENCIADA =================
df_rede_bruta = pd.read_csv(ARQUIVO_REDE, sep=';', dtype=str)
col_uf_rede = 'UF_SIGLA' if 'UF_SIGLA' in df_rede_bruta.columns else 'UF'

contagem_rede = df_rede_bruta.groupby(col_uf_rede).size().reset_index()
contagem_rede.columns = ['uf', 'qtd_parceiros_real']

df_uf = df_nacional.groupby('uf').agg({'leads_reais': 'sum', 'regiao': 'first'}).reset_index()
df_uf = pd.merge(df_uf, contagem_rede, on='uf', how='left').fillna(0).sort_values('leads_reais', ascending=False)

total_leads = df_nacional['leads_reais'].sum()
total_municipios = df_nacional['municipio'].nunique()
total_rede = len(df_rede_bruta)

# ================= 4. GERAÇÃO DO PDF =================
print(f"--- [3/3] Gerando Relatório Visual Executivo ---")
caminho_pdf = os.path.join(PASTA_SAIDA, f"Relatorio_Estrategico_FARMACIA_{MES_ANO}.pdf")

with PdfPages(caminho_pdf) as pdf:
    # PÁGINA 1: DASHBOARD
    fig1 = plt.figure(figsize=(24, 14))
    gs = gridspec.GridSpec(2, 2, figure=fig1, width_ratios=[1.3, 0.9], height_ratios=[1, 1])
    fig1.suptitle(f'INTELIGÊNCIA DE MERCADO NACIONAL: SETOR FARMACÊUTICO ({MES_ANO})', 
                  fontsize=32, fontweight='bold', color=COR_PRIMARIA, y=0.97)

    # Gráfico de Pizza
    ax1 = fig1.add_subplot(gs[0, 0])
    resumo_reg = df_nacional.groupby('regiao')['leads_reais'].sum().sort_values(ascending=False)
    ax1.pie(resumo_reg, labels=resumo_reg.index, autopct='%1.1f%%', startangle=140, 
            colors=sns.color_palette("Blues_r", 5), pctdistance=0.75, 
            textprops={'fontsize': 12, 'fontweight': 'bold'})
    ax1.set_title('CONCENTRAÇÃO DE LEADS POR REGIÃO', fontsize=20, fontweight='bold', color=COR_PRIMARIA, pad=20)

    # Gráfico Misto (UF vs Rede) com Rótulos
    ax2 = fig1.add_subplot(gs[1, 0]); ax2_twin = ax2.twinx()
    sns.barplot(x='uf', y='leads_reais', data=df_uf, ax=ax2, palette="Blues_r", hue='uf', legend=False)
    
    # Rótulos Leads (Barras)
    for i, v in enumerate(df_uf['leads_reais']):
        ax2.text(i, v + (df_uf['leads_reais'].max() * 0.01), fmt_br(v), ha='center', va='bottom', fontsize=8, color=COR_PRIMARIA)

    # Linha Rede + Rótulos (Destaque)
    ax2_twin.plot(df_uf['uf'], df_uf['qtd_parceiros_real'], marker='o', color=COR_DESTAQUE, linewidth=3, label='Rede Atual')
    for i, v in enumerate(df_uf['qtd_parceiros_real']):
        ax2_twin.text(i, v + (df_uf['qtd_parceiros_real'].max() * 0.05), fmt_br(v), 
                      ha='center', va='bottom', fontsize=10, color='white', fontweight='bold',
                      bbox=dict(boxstyle='round,pad=0.3', fc=COR_DESTAQUE, ec='none'))
    
    ax2.set_title('POTENCIAL (LEADS) VS PRESENÇA (REDE ATUAL)', fontsize=18, fontweight='bold', color=COR_PRIMARIA)
    ax2_twin.set_ylim(0, df_uf['qtd_parceiros_real'].max() * 1.6)

    # Ranking Top Cidades
    ax3 = fig1.add_subplot(gs[:, 1])
    top_30 = df_nacional.head(30).copy()
    sns.barplot(x='leads_reais', y='municipio', data=top_30, ax=ax3, palette="mako", hue='municipio', legend=False)
    for i, v in enumerate(top_30['leads_reais']):
        ax3.text(v + (top_30['leads_reais'].max() * 0.01), i, fmt_br(v), color=COR_PRIMARIA, va='center', fontweight='bold', fontsize=10)
    ax3.set_title('TOP 30 MUNICÍPIOS (DENSIDADE)', fontsize=20, fontweight='bold', color=COR_PRIMARIA)

    plt.tight_layout(rect=[0.05, 0.05, 0.95, 0.93]); pdf.savefig(fig1); plt.close()

    # PÁGINA 2: SUMÁRIO E INSIGHTS
    fig2 = plt.figure(figsize=(24, 14)); ax_sum = fig2.add_subplot(111); ax_sum.axis('off')
    fig2.patch.set_facecolor('#F8F9F9')
    ax_sum.text(0.05, 0.92, "SUMÁRIO EXECUTIVO E DIRETRIZES", fontsize=30, fontweight='bold', color=COR_PRIMARIA)
    ax_sum.axhline(y=0.89, xmin=0.05, xmax=0.95, color=COR_PRIMARIA, linewidth=2)

    # KPIs
    kpis = [("MUNICÍPIOS ANALISADOS", total_municipios, 0.05, COR_PRIMARIA), 
            ("POTENCIAL TOTAL (LEADS)", total_leads, 0.35, COR_TERCIARIA), 
            ("REDE CREDENCIADA ATUAL", total_rede, 0.65, COR_DESTAQUE)]
    for label, valor, x, cor in kpis:
        ax_sum.add_patch(plt.Rectangle((x, 0.70), 0.25, 0.12, color='white', ec=cor, lw=2))
        ax_sum.text(x+0.02, 0.78, label, fontsize=14, color='gray', fontweight='bold')
        ax_sum.text(x+0.02, 0.73, fmt_br(valor), fontsize=28, fontweight='bold', color=cor)

    # Seção de Metodologia
    metodologia = (
        "• Processamento: Cruzamento de CEPs de farmácias credenciadas com a base da Receita Federal.\n"
        "• Qualidade: Filtro rigoroso para exclusão de MEIs e Naturezas Jurídicas 2135.\n"
        "• Estratégia de Proximidade: Leads capturados por estarem no mesmo raio de atuação dos parceiros.\n"
        "• Atualização: Dados consolidados para o ciclo estratégico de " + MES_ANO + "."
    )
    ax_sum.text(0.05, 0.60, "NOTAS METODOLÓGICAS", fontsize=22, fontweight='bold', color=COR_PRIMARIA)
    ax_sum.text(0.05, 0.44, metodologia, fontsize=18, color='#333333', linespacing=1.8)

    # Seção de Insights (Adicionada)
    insights = (
        "1. ESTRATÉGIA NACIONAL: Focar expansão nos estados com maior diferencial entre barras e linha.\n"
        "2. PRIORIDADE SUL/SUDESTE: Regiões que apresentam o maior volume bruto de leads qualificados.\n"
        "3. AÇÃO COMERCIAL: Utilizar o ranking Top 30 para prospecção de parceiros âncoras locais.\n"
        "4. ARGUMENTO DE VENDA: Alta densidade de empresas vizinhas a farmácias já credenciadas."
    )
    ax_sum.text(0.05, 0.35, "INSIGHTS PARA A DIRETORIA", fontsize=22, fontweight='bold', color=COR_SECUNDARIA)
    ax_sum.text(0.05, 0.15, insights, fontsize=18, color='#333333', linespacing=1.8, 
                bbox=dict(facecolor='#E8F6F3', edgecolor='none', boxstyle='round,pad=1'))

    pdf.savefig(fig2); plt.close()

print(f"\n✅ RELATÓRIO FINALIZADO: {caminho_pdf}")
os.startfile(caminho_pdf)