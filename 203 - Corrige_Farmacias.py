import pandas as pd
import os

# ================= CONFIGURAÇÕES =================
PASTA_RAIZ = r"C:\Users\Usuario\Documents\OneDrive - Brasil Convênios\Área de Trabalho\Dados\Python\CSVs"
ARQUIVO_ENTRADA = os.path.join(PASTA_RAIZ, "Farmacia.xls")
ARQUIVO_SAIDA = os.path.join(PASTA_RAIZ, "Rede_Credenciada_Farmacias.csv")

# Dicionário de padronização (Mapeamento de Tipos)
MAPA_LOGRADOUROS = {
    'R': 'RUA', 'RUA': 'RUA',
    'AV': 'AVENIDA', 'AVENIDA': 'AVENIDA',
    'TV': 'TRAVESSA', 'TRAVESSA': 'TRAVESSA',
    'QD': 'QUADRA', 'QUADRA': 'QUADRA',
    'PRC': 'PRACA', 'PRAÇA': 'PRACA', 'PC': 'PRACA', 'PCA': 'PRACA',
    'AL': 'ALAMEDA', 'ALAMEDA': 'ALAMEDA',
    'ROD': 'RODOVIA', 'RODOVIA': 'RODOVIA',
    'EST': 'ESTRADA', 'ESTRADA': 'ESTRADA',
    'LGO': 'LARGO', 'LARGO': 'LARGO'
}

print(f"--- Iniciando Processamento com Tipo de Logradouro ---")

try:
    df_raw = pd.read_excel(ARQUIVO_ENTRADA, header=None, engine='xlrd')
except Exception as e:
    print(f"❌ Erro ao abrir o arquivo: {e}"); exit()

dados_finais = []
uf_atual = ""
cidade_atual = ""

for idx, row in df_raw.iterrows():
    col_a = str(row[0]).strip().upper() if pd.notna(row[0]) else ""
    col_b = str(row[1]).strip().upper() if pd.notna(row[1]) else ""
    col_c = str(row[2]).strip().upper() if pd.notna(row[2]) else ""
    col_d = str(row[3]).strip().upper() if pd.notna(row[3]) else ""

    if col_a == "SEGMENTO": continue
    if col_a == "UF":
        uf_atual = col_b
        continue
    if col_a == "CIDADE":
        cidade_atual = col_b
        continue

    if col_c != "" or col_d != "":
        estabelecimento = col_b
        
        # Separação de Endereço e Número
        if "," in col_c:
            partes = col_c.split(",", 1)
            endereco_bruto = partes[0].strip()
            numero = partes[1].strip()
        else:
            endereco_bruto = col_c
            numero = "S/N"

        # --- LÓGICA DO TIPO DE LOGRADOURO ---
        # Pegamos a primeira palavra do endereço para ver se é o Tipo
        partes_endereco = endereco_bruto.split(" ", 1)
        primeira_palavra = partes_endereco[0].replace(".", "") # Remove ponto se houver (ex: R.)
        
        tipo_logradouro = "OUTRO" # Valor padrão caso não identifique
        nome_rua = endereco_bruto # Valor padrão

        if primeira_palavra in MAPA_LOGRADOUROS:
            tipo_logradouro = MAPA_LOGRADOUROS[primeira_palavra]
            # Se identificou o tipo, o nome da rua passa a ser o restante da frase
            if len(partes_endereco) > 1:
                nome_rua = partes_endereco[1].strip()
        
        bairro = col_d

        dados_finais.append({
            'UF': uf_atual,
            'Cidade': cidade_atual,
            'Estabelecimento': estabelecimento,
            'Tipo_Logradouro': tipo_logradouro,
            'Endereco': nome_rua,
            'Numero': numero,
            'Bairro': bairro
        })

df_final = pd.DataFrame(dados_finais)
df_final = df_final.drop_duplicates()

# Reorganizando a ordem das colunas para ficar intuitivo
colunas_ordem = ['UF', 'Cidade', 'Estabelecimento', 'Tipo_Logradouro', 'Endereco', 'Numero', 'Bairro']
df_final = df_final[colunas_ordem]

df_final.to_csv(ARQUIVO_SAIDA, sep=';', index=False, encoding='utf-8-sig')

print(f"--- Processo Concluído com Sucesso! ---")
print(f"Total de Farmácias Processadas: {len(df_final)}")