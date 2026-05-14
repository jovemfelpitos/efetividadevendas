import hmac
import io
import os

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


# --- 1. CONFIGURAÇÃO VISUAL ---
st.set_page_config(
    page_title="Sath Analytics - Multi-Bases",
    page_icon="📊",
    layout="wide",
)

st.markdown(
    """
    <style>
        .block-container {padding-top: 1rem; padding-bottom: 0rem;}
        div[data-testid="stMetricValue"] {font-size: 1.6rem;}
    </style>
""",
    unsafe_allow_html=True,
)


# --- 2. SEGURANÇA E CONEXÃO ---
def ler_secret(caminho, env_var=None):
    try:
        valor = st.secrets
        for parte in caminho.split("."):
            valor = valor[parte]
        if valor:
            return str(valor)
    except Exception:
        pass

    if env_var:
        return os.getenv(env_var)
    return None


def autenticar_usuario():
    senha_app = ler_secret("app.password", "APP_PASSWORD")

    if not senha_app:
        st.error("Configure uma senha de acesso em st.secrets antes de usar o sistema.")
        st.info("Use a seção [app] com a chave password. Veja DEPLOY_SUPABASE.md.")
        st.stop()

    if st.session_state.get("autenticado"):
        return

    st.title("Acesso ao Sath Analytics")
    with st.form("form_login"):
        senha_digitada = st.text_input("Senha de acesso", type="password")
        btn_entrar = st.form_submit_button("Entrar")

    if btn_entrar:
        if hmac.compare_digest(senha_digitada, senha_app):
            st.session_state["autenticado"] = True
            st.rerun()
        else:
            st.error("Senha inválida.")

    st.stop()


@st.cache_resource(show_spinner=False)
def get_engine():
    database_url = ler_secret("database.url", "DATABASE_URL")

    if not database_url:
        return None

    return create_engine(
        database_url,
        connect_args={"sslmode": "require"},
        pool_pre_ping=True,
        pool_recycle=300,
    )


def obter_engine_ou_parar():
    engine = get_engine()

    if engine is None:
        st.error("Configure a URL do banco Postgres/Supabase em st.secrets.")
        st.info("Use a seção [database] com a chave url. Veja DEPLOY_SUPABASE.md.")
        st.stop()

    return engine


def inicializar_banco():
    engine = obter_engine_ou_parar()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS bases_relatorios (
                    id BIGSERIAL PRIMARY KEY,
                    nome_da_base TEXT NOT NULL UNIQUE
                        CHECK (length(trim(nome_da_base)) BETWEEN 1 AND 120),
                    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS vendas_relatorios (
                    id BIGSERIAL PRIMARY KEY,
                    base_id BIGINT NOT NULL REFERENCES bases_relatorios(id) ON DELETE CASCADE,
                    equipe TEXT NOT NULL,
                    operador TEXT NOT NULL,
                    produto TEXT NOT NULL,
                    status TEXT NOT NULL,
                    valor_entrada NUMERIC(14, 2) NOT NULL DEFAULT 0,
                    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_vendas_relatorios_base_produto
                ON vendas_relatorios (base_id, produto)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_bases_relatorios_nome
                ON bases_relatorios (nome_da_base)
                """
            )
        )


# --- 3. FUNÇÕES DE SUPORTE ---
def limpar_dinheiro(valor):
    if isinstance(valor, (int, float)):
        return float(valor)
    if isinstance(valor, str):
        limpo = valor.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
        try:
            return float(limpo)
        except ValueError:
            return 0.0
    return 0.0


def normalizar_status(texto):
    if not isinstance(texto, str):
        return "Outros"
    texto = texto.upper().strip()
    texto = texto.replace("Í", "I").replace("É", "E").replace("Ã", "A").replace("Ó", "O")

    if any(x in texto for x in ["CONCLU", "PAGO", "APROV", "OK"]):
        return "Concluído"
    if any(x in texto for x in ["RECUS", "CANCEL", "NEGAD", "DEVOL"]):
        return "Recusado"
    if any(x in texto for x in ["ANDAMENT", "ANALISE", "PENDEN", "AGUARD", "ESTEIRA", "DIGITA", "IMPLANT"]):
        return "Em Andamento"

    return "Outros"


def normalizar_texto_planilha(serie, padrao):
    return (
        serie.fillna(padrao)
        .astype(str)
        .str.strip()
        .str.slice(0, 255)
        .replace("", padrao)
    )


def normalizar_nome_base(nome_base):
    return str(nome_base or "").strip()[:120]


def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Relatorio")
    return output.getvalue()


def listar_bases():
    engine = obter_engine_ou_parar()
    with engine.connect() as conn:
        df = pd.read_sql_query(
            text(
                """
                SELECT nome_da_base
                FROM bases_relatorios
                ORDER BY criado_em ASC, nome_da_base ASC
                """
            ),
            conn,
        )
    return df["nome_da_base"].tolist()


def excluir_base(nome_base):
    engine = obter_engine_ou_parar()
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM bases_relatorios WHERE nome_da_base = :nome_da_base"),
            {"nome_da_base": nome_base},
        )


def salvar_base(nome_base, df):
    required = ["equipe", "operador", "produto", "status", "valor_entrada"]
    dados = df[required].copy()
    dados["equipe"] = normalizar_texto_planilha(dados["equipe"], "Sem equipe")
    dados["operador"] = normalizar_texto_planilha(dados["operador"], "Sem consultor")
    dados["produto"] = normalizar_texto_planilha(dados["produto"], "Sem produto")
    dados["valor_entrada"] = dados["valor_entrada"].apply(limpar_dinheiro)
    dados["status"] = dados["status"].apply(normalizar_status)

    engine = obter_engine_ou_parar()
    with engine.begin() as conn:
        base_id = conn.execute(
            text(
                """
                INSERT INTO bases_relatorios (nome_da_base)
                VALUES (:nome_da_base)
                RETURNING id
                """
            ),
            {"nome_da_base": nome_base},
        ).scalar_one()

        dados.insert(0, "base_id", base_id)
        dados.to_sql(
            "vendas_relatorios",
            conn,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=1000,
        )


def listar_produtos_da_base(nome_base):
    engine = obter_engine_ou_parar()
    with engine.connect() as conn:
        df = pd.read_sql_query(
            text(
                """
                SELECT DISTINCT v.produto
                FROM vendas_relatorios v
                INNER JOIN bases_relatorios b ON b.id = v.base_id
                WHERE b.nome_da_base = :nome_da_base
                ORDER BY v.produto ASC
                """
            ),
            conn,
            params={"nome_da_base": nome_base},
        )
    return df["produto"].tolist()


def buscar_dashboard_por_equipe(nome_base, produto):
    engine = obter_engine_ou_parar()
    with engine.connect() as conn:
        return pd.read_sql_query(
            text(
                """
                SELECT
                    v.equipe,
                    SUM(v.valor_entrada)::float AS "Volume",
                    SUM(CASE WHEN v.status = 'Concluído' THEN v.valor_entrada ELSE 0 END)::float AS "Concluido",
                    SUM(CASE WHEN v.status = 'Em Andamento' THEN v.valor_entrada ELSE 0 END)::float AS "EmAndamento",
                    SUM(CASE WHEN v.status = 'Recusado' THEN v.valor_entrada ELSE 0 END)::float AS "Recusado"
                FROM vendas_relatorios v
                INNER JOIN bases_relatorios b ON b.id = v.base_id
                WHERE b.nome_da_base = :nome_da_base
                  AND v.produto = :produto
                GROUP BY v.equipe
                """
            ),
            conn,
            params={"nome_da_base": nome_base, "produto": produto},
        )


def buscar_dashboard_por_consultor(nome_base, produto):
    engine = obter_engine_ou_parar()
    with engine.connect() as conn:
        return pd.read_sql_query(
            text(
                """
                SELECT
                    v.equipe,
                    v.operador,
                    SUM(v.valor_entrada)::float AS "Volume",
                    SUM(CASE WHEN v.status = 'Concluído' THEN v.valor_entrada ELSE 0 END)::float AS "Concluido",
                    SUM(CASE WHEN v.status = 'Em Andamento' THEN v.valor_entrada ELSE 0 END)::float AS "EmAndamento",
                    SUM(CASE WHEN v.status = 'Recusado' THEN v.valor_entrada ELSE 0 END)::float AS "Recusado"
                FROM vendas_relatorios v
                INNER JOIN bases_relatorios b ON b.id = v.base_id
                WHERE b.nome_da_base = :nome_da_base
                  AND v.produto = :produto
                GROUP BY v.equipe, v.operador
                ORDER BY v.equipe, "Volume" DESC
                """
            ),
            conn,
            params={"nome_da_base": nome_base, "produto": produto},
        )


# --- 4. INICIALIZAÇÃO ---
autenticar_usuario()

try:
    inicializar_banco()
except SQLAlchemyError:
    st.error("Não foi possível conectar ou preparar o banco de dados.")
    st.info("Confira a DATABASE_URL do Supabase e se o projeto está ativo.")
    st.stop()


# --- 5. BARRA LATERAL (GERENCIAMENTO DE BASES) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2704/2704027.png", width=50)
    st.title("Gerenciador de Bases")

    with st.form("form_importacao"):
        st.subheader("1. Nova Importação")
        nome_base = st.text_input("Nome do Relatório (Ex: Nov/2023)", placeholder="Digite um nome...")
        uploaded_file = st.file_uploader("Planilha (.xlsx)", type=["xlsx"])
        btn_salvar = st.form_submit_button("📥 Salvar no Banco")

    bases_salvas = listar_bases()

    if bases_salvas:
        st.markdown("---")
        with st.form("form_exclusao"):
            st.subheader("2. Excluir Relatório")
            base_del = st.selectbox("Selecione a base:", bases_salvas)
            btn_del = st.form_submit_button("🗑️ Apagar Base")

            if btn_del:
                excluir_base(base_del)
                st.success(f"Base '{base_del}' apagada!")
                st.rerun()


# --- 6. LÓGICA DE PROCESSAMENTO (UPLOAD) ---
if btn_salvar:
    nome_base = normalizar_nome_base(nome_base)

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
                "Equipe": "equipe",
                "Consultor": "operador",
                "Produto": "produto",
                "Status": "status",
                "Valor": "valor_entrada",
                "Meta": "valor_entrada",
            }
            df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)

            required = ["equipe", "operador", "produto", "status", "valor_entrada"]
            if not all(c in df.columns for c in required):
                st.error(f"Faltam colunas na planilha: {required}")
            else:
                salvar_base(nome_base, df)
                st.toast(f"Base '{nome_base}' salva com sucesso!", icon="✅")
                st.rerun()

        except IntegrityError:
            st.error("Já existe uma base com esse nome. Exclua a antiga ou escolha outro nome.")
        except Exception as e:
            st.error(f"Erro ao processar: {e}")


# --- 7. FUNÇÃO CONSTRUTORA DO DASHBOARD ---
def render_dashboard(base_selecionada, produto_selecionado):
    df_dash = buscar_dashboard_por_equipe(base_selecionada, produto_selecionado)

    total_vol = df_dash["Volume"].sum()
    total_conc = df_dash["Concluido"].sum()
    total_and = df_dash["EmAndamento"].sum()
    total_rec = df_dash["Recusado"].sum()

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Volume Entrada", f"R$ {total_vol:,.2f}")

    if total_vol > 0:
        col2.metric("Efetividade", f"{(total_conc / total_vol * 100):.2f}%", f"R$ {total_conc:,.2f}")
        col3.metric("Em Andamento", f"{(total_and / total_vol * 100):.2f}%", f"R$ {total_and:,.2f}", delta_color="off")
        col4.metric("Recusado", f"{(total_rec / total_vol * 100):.2f}%", f"R$ {total_rec:,.2f}", delta_color="inverse")
        col5.download_button(
            "📥 Baixar Excel",
            data=to_excel(df_dash),
            file_name=f"{base_selecionada}_{produto_selecionado}.xlsx",
            mime="application/vnd.ms-excel",
            key=f"btn_{base_selecionada}_{produto_selecionado}",
        )

    st.divider()

    st.subheader("📊 Por Equipe")
    df_dash["% Efetividade"] = (df_dash["Concluido"] / df_dash["Volume"] * 100).fillna(0)
    df_dash["% Em Andamento"] = (df_dash["EmAndamento"] / df_dash["Volume"] * 100).fillna(0)
    df_dash["% Recusa"] = (df_dash["Recusado"] / df_dash["Volume"] * 100).fillna(0)
    df_dash["% Repr. Empresa"] = (df_dash["Volume"] / total_vol * 100).fillna(0)

    st.dataframe(
        df_dash.sort_values("Volume", ascending=False)
        .style.format(
            {
                "Volume": "R$ {:,.2f}",
                "Concluido": "R$ {:,.2f}",
                "EmAndamento": "R$ {:,.2f}",
                "Recusado": "R$ {:,.2f}",
                "% Efetividade": "{:.2f}%",
                "% Em Andamento": "{:.2f}%",
                "% Recusa": "{:.2f}%",
                "% Repr. Empresa": "{:.2f}%",
            }
        )
        .background_gradient(subset=["% Efetividade"], cmap="Greens"),
        use_container_width=True,
    )

    st.divider()
    st.subheader("👤 Detalhe por Consultor")

    df_cons = buscar_dashboard_por_consultor(base_selecionada, produto_selecionado)
    df_cons["% Efetividade"] = (df_cons["Concluido"] / df_cons["Volume"] * 100).fillna(0)
    df_cons["% Em Andamento"] = (df_cons["EmAndamento"] / df_cons["Volume"] * 100).fillna(0)
    df_cons["% Recusa"] = (df_cons["Recusado"] / df_cons["Volume"] * 100).fillna(0)

    lista_equipes = df_cons["equipe"].unique()
    equipes_selecionadas = st.multiselect(
        "Filtrar Equipes:",
        options=lista_equipes,
        default=lista_equipes,
        key=f"ms_{base_selecionada}_{produto_selecionado}",
    )

    df_filtrado = df_cons if not equipes_selecionadas else df_cons[df_cons["equipe"].isin(equipes_selecionadas)]

    st.dataframe(
        df_filtrado.style.format(
            {
                "Volume": "R$ {:,.2f}",
                "Concluido": "R$ {:,.2f}",
                "EmAndamento": "R$ {:,.2f}",
                "Recusado": "R$ {:,.2f}",
                "% Efetividade": "{:.2f}%",
                "% Em Andamento": "{:.2f}%",
                "% Recusa": "{:.2f}%",
            }
        ),
        use_container_width=True,
    )


# --- 8. EXIBIÇÃO PRINCIPAL (ABAS DINÂMICAS) ---
st.title("🚀 Relatório Multi-Bases")

if bases_salvas:
    abas_principais = st.tabs([f"📁 {b}" for b in bases_salvas])

    for idx_base, base_atual in enumerate(bases_salvas):
        with abas_principais[idx_base]:
            st.markdown(f"### Visualizando: **{base_atual}**")

            produtos_da_base = listar_produtos_da_base(base_atual)

            if produtos_da_base:
                abas_secundarias = st.tabs([f"📦 {p}" for p in produtos_da_base])

                for idx_prod, produto_atual in enumerate(produtos_da_base):
                    with abas_secundarias[idx_prod]:
                        render_dashboard(base_atual, produto_atual)
else:
    st.info("👈 Nenhuma base encontrada. Use a barra lateral para importar seu primeiro relatório.")
