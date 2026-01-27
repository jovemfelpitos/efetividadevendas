import streamlit as st
import pandas as pd
import sqlite3
import io

# --- 1. CONFIGURAÇÃO VISUAL ---
st.set_page_config(
    page_title="Sath Analytics - Efetividade",
    page_icon="📊",
    layout="wide"
)

st.markdown("""
    <style>
        .block-container {padding-top: 1rem; padding-bottom: 0rem;}
        div[data-testid="stMetricValue"] {font-size: 1.8rem;}
    </style>
""", unsafe_allow_html=True)

DB_FILE = "vendas_final.db"

# --- 2. FUNÇÕES DE SUPORTE ---
def get_connection():
    return sqlite3.connect(DB_FILE)

def inicializar_banco():
    conn = get_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS vendas (
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
    
    if any(x in texto for x in ['CONCLU', 'PAGO', 'APROV', 'OK']):
        return 'Concluído'
    
    if any(x in texto for x in ['RECUS', 'CANCEL', 'NEGAD', 'DEVOL']):
        return 'Recusado'
        
    return "Outros"

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Relatorio')
    return output.getvalue()

# --- 3. BARRA LATERAL ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2704/2704027.png", width=50)
    st.title("Painel de Controle")
    
    uploaded_file = st.file_uploader("Importar Planilha (.xlsx)", type=["xlsx"])
    
    st.markdown("---")
    if st.button("🗑️ Limpar Base de Dados", type="primary"):
        conn = get_connection()
        conn.execute("DELETE FROM vendas")
        conn.commit()
        conn.close()
        st.toast("Base limpa!", icon="🧹")
        st.rerun()

# --- 4. PROCESSAMENTO ---
if uploaded_file:
    inicializar_banco()
    try:
        df = pd.read_excel(uploaded_file)
        
        col_map = {
            'Equipe': 'equipe', 'Consultor': 'operador', 
            'Produto': 'produto', 'Status': 'status', 
            'Valor': 'valor_entrada', 'Meta': 'valor_entrada',
            'Valor Proposta': 'valor_entrada'
        }
        df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)
        
        required = ['equipe', 'operador', 'produto', 'status', 'valor_entrada']
        if not all(c in df.columns for c in required):
            st.error(f"Faltam colunas: {required}")
            st.stop()
            
        df['valor_entrada'] = df['valor_entrada'].apply(limpar_dinheiro)
        df['status'] = df['status'].apply(normalizar_status)
        
        conn = get_connection()
        conn.execute("DELETE FROM vendas")
        df[required].to_sql('vendas', conn, if_exists='append', index=False)
        conn.close()
        st.toast("Sucesso!", icon="✅")
        
    except Exception as e:
        st.error(f"Erro: {e}")

# --- 5. DASHBOARD ---
st.title("🚀 Relatório de Performance")

conn = get_connection()
try:
    has_data = pd.read_sql("SELECT count(*) as qtd FROM vendas", conn)['qtd'][0] > 0
except:
    has_data = False

if has_data:
    produtos = pd.read_sql("SELECT DISTINCT produto FROM vendas", conn)['produto'].tolist()
    abas = st.tabs([f"📦 {p}" for p in produtos])
    
    for i, produto in enumerate(produtos):
        with abas[i]:
            # --- QUERY GERAL ---
            df_dash = pd.read_sql(f"""
                SELECT 
                    equipe,
                    SUM(valor_entrada) as Volume,
                    SUM(CASE WHEN status = 'Concluído' THEN valor_entrada ELSE 0 END) as Concluido,
                    SUM(CASE WHEN status = 'Recusado' THEN valor_entrada ELSE 0 END) as Recusado
                FROM vendas WHERE produto = '{produto}'
                GROUP BY equipe
            """, conn)
            
            total_vol = df_dash['Volume'].sum()
            total_conc = df_dash['Concluido'].sum()
            total_rec = df_dash['Recusado'].sum()
            
            # --- KPIs ---
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Volume Entrada", f"R$ {total_vol:,.2f}")
            if total_vol > 0:
                perc_conc = (total_conc / total_vol * 100)
                perc_rec = (total_rec / total_vol * 100)
                col2.metric("Efetividade Global", f"{perc_conc:.2f}%", f"R$ {total_conc:,.2f}")
                col3.metric("Taxa de Recusa", f"{perc_rec:.2f}%", f"R$ {total_rec:,.2f}", delta_color="inverse")
                col4.download_button(
                    label="📥 Baixar Excel",
                    data=to_excel(df_dash),
                    file_name=f'relatorio_{produto}.xlsx',
                    mime='application/vnd.ms-excel'
                )
            
            st.divider()
            
            # --- TABELA EQUIPE ---
            st.subheader("📊 Por Equipe")
            df_dash['% Efetividade'] = (df_dash['Concluido'] / df_dash['Volume'] * 100).fillna(0)
            df_dash['% Recusa'] = (df_dash['Recusado'] / df_dash['Volume'] * 100).fillna(0)
            df_dash['% Repr. Empresa'] = (df_dash['Volume'] / total_vol * 100).fillna(0)
            df_dash = df_dash.sort_values('Volume', ascending=False)
            
            st.dataframe(df_dash.style.format({
                'Volume': 'R$ {:,.2f}', 'Concluido': 'R$ {:,.2f}', 'Recusado': 'R$ {:,.2f}',
                '% Efetividade': '{:.2f}%', '% Recusa': '{:.2f}%', '% Repr. Empresa': '{:.2f}%'
            }).background_gradient(subset=['% Efetividade'], cmap="Greens"), use_container_width=True)
            
            # --- TABELA CONSULTOR (COM FILTRO NOVO) ---
            st.divider()
            st.subheader("👤 Detalhe por Consultor")
            
            # 1. Carrega todos os consultores do banco primeiro
            df_cons = pd.read_sql(f"""
                SELECT 
                    equipe, operador,
                    SUM(valor_entrada) as Volume,
                    SUM(CASE WHEN status = 'Concluído' THEN valor_entrada ELSE 0 END) as Concluido,
                    SUM(CASE WHEN status = 'Recusado' THEN valor_entrada ELSE 0 END) as Recusado
                FROM vendas WHERE produto = '{produto}'
                GROUP BY equipe, operador ORDER BY equipe, Volume DESC
            """, conn)
            
            # 2. Prepara o cálculo das porcentagens
            df_cons['% Efetividade'] = (df_cons['Concluido'] / df_cons['Volume'] * 100).fillna(0)
            df_cons['% Recusa'] = (df_cons['Recusado'] / df_cons['Volume'] * 100).fillna(0)
            
            # 3. O FILTRO DE EQUIPE (A MÁGICA AQUI)
            # Pega lista única de equipes que existem nesse produto
            lista_equipes = df_cons['equipe'].unique()
            
            # Cria o componente multiselect
            # default=lista_equipes faz com que comece com TODAS marcadas
            equipes_selecionadas = st.multiselect(
                f"Filtrar Equipes ({produto}):",
                options=lista_equipes,
                default=lista_equipes,
                placeholder="Selecione as equipes..."
            )
            
            # Se o usuário limpar tudo, mostramos tudo (ou nada, se preferir tire o if)
            if not equipes_selecionadas:
                df_filtrado = df_cons # Fallback: mostra tudo se estiver vazio
            else:
                df_filtrado = df_cons[df_cons['equipe'].isin(equipes_selecionadas)]

            # 4. Mostra a tabela filtrada
            st.dataframe(df_filtrado.style.format({
                'Volume': 'R$ {:,.2f}', 'Concluido': 'R$ {:,.2f}', 'Recusado': 'R$ {:,.2f}',
                '% Efetividade': '{:.2f}%', '% Recusa': '{:.2f}%'
            }), use_container_width=True)

else:
    st.info("👈 Faça o upload da planilha para começar.")