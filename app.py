import streamlit as st
import pandas as pd
import sqlite3
import io

# --- 1. CONFIGURAÇÃO VISUAL ---
st.set_page_config(
    page_title="Sath Analytics - Multi-Bases",
    page_icon="📊",
    layout="wide"
)

st.markdown("""
    <style>
        .block-container {padding-top: 1rem; padding-bottom: 0rem;}
        div[data-testid="stMetricValue"] {font-size: 1.6rem;} 
    </style>
""", unsafe_allow_html=True)

DB_FILE = "vendas_final.db"

# --- 2. FUNÇÕES DE SUPORTE ---
def get_connection():
    return sqlite3.connect(DB_FILE)

def inicializar_banco():
    conn = get_connection()
    # NOVA COLUNA ADICIONADA: nome_da_base
    conn.execute('''
        CREATE TABLE IF NOT EXISTS vendas (
            nome_da_base TEXT,
            equipe TEXT,
            operador TEXT,
            produto TEXT,
            status TEXT,
            valor_entrada REAL
        )
    ''')
    conn.commit()
    conn.close()

def limpar_dinheiro(valor):
    if isinstance(valor, (int, float)): return float(valor)
    if isinstance(valor, str):
        limpo = valor.replace('R$', '').replace(' ', '').replace('.', '').replace(',', '.')
        try: return float(limpo)
        except: return 0.0
    return 0.0

def normalizar_status(texto):
    if not isinstance(texto, str): return "Outros"
    texto = texto.upper().strip()
    texto = texto.replace('Í', 'I').replace('É', 'E').replace('Ã', 'A').replace('Ó', 'O')
    
    if any(x in texto for x in ['CONCLU', 'PAGO', 'APROV', 'OK']): return 'Concluído'
    if any(x in texto for x in ['RECUS', 'CANCEL', 'NEGAD', 'DEVOL']): return 'Recusado'
    if any(x in texto for x in ['ANDAMENT', 'ANALISE', 'PENDEN', 'AGUARD', 'ESTEIRA', 'DIGITA', 'IMPLANT']): return 'Em Andamento'
        
    return "Outros"

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Relatorio')
    return output.getvalue()

inicializar_banco() # Garante que o banco existe ao abrir a página

# --- 3. BARRA LATERAL (GERENCIAMENTO DE BASES) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2704/2704027.png", width=50)
    st.title("Gerenciador de Bases")
    
    # Formulário de Importação (Só envia quando clica no botão)
    with st.form("form_importacao"):
        st.subheader("1. Nova Importação")
        nome_base = st.text_input("Nome do Relatório (Ex: Nov/2023)", placeholder="Digite um nome...")
        uploaded_file = st.file_uploader("Planilha (.xlsx)", type=["xlsx"])
        btn_salvar = st.form_submit_button("📥 Salvar no Banco")

    # Verifica quais bases existem para o botão de excluir
    conn = get_connection()
    try:
        bases_salvas = pd.read_sql("SELECT DISTINCT nome_da_base FROM vendas", conn)['nome_da_base'].tolist()
    except:
        bases_salvas = []
    conn.close()

    # Formulário de Exclusão
    if bases_salvas:
        st.markdown("---")
        with st.form("form_exclusao"):
            st.subheader("2. Excluir Relatório")
            base_del = st.selectbox("Selecione a base:", bases_salvas)
            btn_del = st.form_submit_button("🗑️ Apagar Base")
            
            if btn_del:
                conn = get_connection()
                conn.execute(f"DELETE FROM vendas WHERE nome_da_base = '{base_del}'")
                conn.commit()
                conn.close()
                st.success(f"Base '{base_del}' apagada!")
                st.rerun()

# --- 4. LÓGICA DE PROCESSAMENTO (UPLOAD) ---
if btn_salvar:
    if not nome_base:
        st.sidebar.error("Você precisa dar um nome para a base!")
    elif not uploaded_file:
        st.sidebar.error("Você precisa anexar o arquivo!")
    elif nome_base in bases_salvas:
        st.sidebar.error("Já existe uma base com esse nome. Exclua a antiga ou escolha outro nome.")
    else:
        try:
            df = pd.read_excel(uploaded_file)
            col_map = {
                'Equipe': 'equipe', 'Consultor': 'operador', 
                'Produto': 'produto', 'Status': 'status', 
                'Valor': 'valor_entrada', 'Meta': 'valor_entrada'
            }
            df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)
            
            required = ['equipe', 'operador', 'produto', 'status', 'valor_entrada']
            if not all(c in df.columns for c in required):
                st.error(f"Faltam colunas na planilha: {required}")
            else:
                df['valor_entrada'] = df['valor_entrada'].apply(limpar_dinheiro)
                df['status'] = df['status'].apply(normalizar_status)
                
                # ADICIONA O CARIMBO DA BASE
                df['nome_da_base'] = nome_base
                
                conn = get_connection()
                # AQUI É O PULO DO GATO: Tiramos o DELETE! Ele só faz append agora.
                df[['nome_da_base'] + required].to_sql('vendas', conn, if_exists='append', index=False)
                conn.close()
                
                st.toast(f"Base '{nome_base}' salva com sucesso!", icon="✅")
                st.rerun() # Atualiza a tela para mostrar a nova aba
                
        except Exception as e:
            st.error(f"Erro ao processar: {e}")

# --- 5. FUNÇÃO CONSTRUTORA DO DASHBOARD ---
# Criei essa função para não repetir código toda hora
def render_dashboard(base_selecionada, produto_selecionado):
    conn = get_connection()
    
    # Query filtrando BASE e PRODUTO
    df_dash = pd.read_sql(f"""
        SELECT 
            equipe,
            SUM(valor_entrada) as Volume,
            SUM(CASE WHEN status = 'Concluído' THEN valor_entrada ELSE 0 END) as Concluido,
            SUM(CASE WHEN status = 'Em Andamento' THEN valor_entrada ELSE 0 END) as EmAndamento,
            SUM(CASE WHEN status = 'Recusado' THEN valor_entrada ELSE 0 END) as Recusado
        FROM vendas 
        WHERE nome_da_base = '{base_selecionada}' AND produto = '{produto_selecionado}'
        GROUP BY equipe
    """, conn)
    
    total_vol = df_dash['Volume'].sum()
    total_conc = df_dash['Concluido'].sum()
    total_and = df_dash['EmAndamento'].sum() 
    total_rec = df_dash['Recusado'].sum()
    
    # KPIs
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Volume Entrada", f"R$ {total_vol:,.2f}")
    
    if total_vol > 0:
        col2.metric("Efetividade", f"{(total_conc / total_vol * 100):.2f}%", f"R$ {total_conc:,.2f}")
        col3.metric("Em Andamento", f"{(total_and / total_vol * 100):.2f}%", f"R$ {total_and:,.2f}", delta_color="off")
        col4.metric("Recusado", f"{(total_rec / total_vol * 100):.2f}%", f"R$ {total_rec:,.2f}", delta_color="inverse")
        col5.download_button("📥 Baixar Excel", data=to_excel(df_dash), file_name=f'{base_selecionada}_{produto_selecionado}.xlsx', mime='application/vnd.ms-excel', key=f"btn_{base_selecionada}_{produto_selecionado}")
    
    st.divider()
    
    # Tabela Equipe
    st.subheader("📊 Por Equipe")
    df_dash['% Efetividade'] = (df_dash['Concluido'] / df_dash['Volume'] * 100).fillna(0)
    df_dash['% Em Andamento'] = (df_dash['EmAndamento'] / df_dash['Volume'] * 100).fillna(0)
    df_dash['% Recusa'] = (df_dash['Recusado'] / df_dash['Volume'] * 100).fillna(0)
    df_dash['% Repr. Empresa'] = (df_dash['Volume'] / total_vol * 100).fillna(0)
    
    st.dataframe(df_dash.sort_values('Volume', ascending=False).style.format({
        'Volume': 'R$ {:,.2f}', 'Concluido': 'R$ {:,.2f}', 'EmAndamento': 'R$ {:,.2f}', 'Recusado': 'R$ {:,.2f}',
        '% Efetividade': '{:.2f}%', '% Em Andamento': '{:.2f}%', '% Recusa': '{:.2f}%', '% Repr. Empresa': '{:.2f}%'
    }).background_gradient(subset=['% Efetividade'], cmap="Greens"), use_container_width=True)
    
    # Tabela Consultor
    st.divider()
    st.subheader("👤 Detalhe por Consultor")
    
    df_cons = pd.read_sql(f"""
        SELECT 
            equipe, operador,
            SUM(valor_entrada) as Volume,
            SUM(CASE WHEN status = 'Concluído' THEN valor_entrada ELSE 0 END) as Concluido,
            SUM(CASE WHEN status = 'Em Andamento' THEN valor_entrada ELSE 0 END) as EmAndamento,
            SUM(CASE WHEN status = 'Recusado' THEN valor_entrada ELSE 0 END) as Recusado
        FROM vendas 
        WHERE nome_da_base = '{base_selecionada}' AND produto = '{produto_selecionado}'
        GROUP BY equipe, operador ORDER BY equipe, Volume DESC
    """, conn)
    
    df_cons['% Efetividade'] = (df_cons['Concluido'] / df_cons['Volume'] * 100).fillna(0)
    df_cons['% Em Andamento'] = (df_cons['EmAndamento'] / df_cons['Volume'] * 100).fillna(0)
    df_cons['% Recusa'] = (df_cons['Recusado'] / df_cons['Volume'] * 100).fillna(0)
    
    lista_equipes = df_cons['equipe'].unique()
    equipes_selecionadas = st.multiselect(f"Filtrar Equipes:", options=lista_equipes, default=lista_equipes, key=f"ms_{base_selecionada}_{produto_selecionado}")
    
    df_filtrado = df_cons if not equipes_selecionadas else df_cons[df_cons['equipe'].isin(equipes_selecionadas)]
    
    st.dataframe(df_filtrado.style.format({
        'Volume': 'R$ {:,.2f}', 'Concluido': 'R$ {:,.2f}', 'EmAndamento': 'R$ {:,.2f}', 'Recusado': 'R$ {:,.2f}',
        '% Efetividade': '{:.2f}%', '% Em Andamento': '{:.2f}%', '% Recusa': '{:.2f}%'
    }), use_container_width=True)

    conn.close()

# --- 6. EXIBIÇÃO PRINCIPAL (ABAS DINÂMICAS) ---
st.title("🚀 Relatório Multi-Bases")

if bases_salvas:
    # 1. Cria as Abas Principais (Uma para cada arquivo/mês importado)
    abas_principais = st.tabs([f"📁 {b}" for b in bases_salvas])
    
    for idx_base, base_atual in enumerate(bases_salvas):
        with abas_principais[idx_base]:
            st.markdown(f"### Visualizando: **{base_atual}**")
            
            # Pega os produtos que existem DENTRO dessa base específica
            conn = get_connection()
            produtos_da_base = pd.read_sql(f"SELECT DISTINCT produto FROM vendas WHERE nome_da_base = '{base_atual}'", conn)['produto'].tolist()
            conn.close()
            
            if produtos_da_base:
                # 2. Cria as Sub-Abas (Cartão, Margem) dentro da Aba da Base
                abas_secundarias = st.tabs([f"📦 {p}" for p in produtos_da_base])
                
                for idx_prod, produto_atual in enumerate(produtos_da_base):
                    with abas_secundarias[idx_prod]:
                        # Chama aquela função gigante que criamos acima!
                        render_dashboard(base_atual, produto_atual)
else:
    st.info("👈 Nenhuma base encontrada. Use a barra lateral para importar seu primeiro relatório.")
