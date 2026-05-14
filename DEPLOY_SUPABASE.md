# Deploy com Supabase/Postgres

Este app agora usa Postgres externo em vez de um arquivo SQLite local. Assim os relatorios continuam salvos mesmo quando o Streamlit Cloud dorme, reinicia ou redeploya.

## 1. Criar o banco no Supabase

1. Crie um projeto no Supabase.
2. Abra **Project Settings > Database**.
3. Copie a connection string do modo **Transaction pooler** ou **Session pooler**.
4. Use sempre SSL. A aplicacao ja força `sslmode=require` na conexao.

## 2. Configurar secrets no Streamlit Cloud

Em **App > Settings > Secrets**, cadastre:

```toml
[database]
url = "postgresql://USUARIO:SENHA@HOST:6543/postgres"

[app]
password = "uma-senha-forte-para-entrar-no-sistema"
```

Nunca suba `.streamlit/secrets.toml` para o GitHub. O `.gitignore` ja protege esse arquivo.

## 3. Segurança obrigatoria

- Use uma senha forte no Supabase e uma senha diferente em `[app].password`.
- Nao compartilhe a connection string do banco.
- Se a connection string vazar, rotacione a senha do banco imediatamente no Supabase.
- Deixe o app do Streamlit privado quando possivel.
- A senha do app protege a tela, mas nao substitui login por usuario. Se varias pessoas forem usar, o ideal é evoluir para usuarios individuais.
- Quem tiver a senha do app consegue subir e apagar bases. Para controle por usuario, sera necessario adicionar autenticacao e permissao por perfil.
- Backups devem ficar ativos no Supabase, principalmente antes de importar bases grandes ou apagar relatorios.

## 4. O que o app cria no banco

Na primeira execucao, o app cria automaticamente:

- `bases_relatorios`: cadastro de cada relatorio importado.
- `vendas_relatorios`: linhas processadas das planilhas.

As exclusoes usam chave estrangeira com `ON DELETE CASCADE`: apagar uma base remove tambem as vendas relacionadas.
