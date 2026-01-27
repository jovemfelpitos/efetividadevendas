# Usa uma imagem leve do Python
FROM python:3.9-slim

# Define a pasta de trabalho dentro do container
WORKDIR /app

# Copia os arquivos da sua pasta para o container
COPY . .

# Instala as dependências
RUN pip install --no-cache-dir -r requirements.txt

# Expõe a porta que o Streamlit usa
EXPOSE 8501

# Comando para rodar o app
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0"]