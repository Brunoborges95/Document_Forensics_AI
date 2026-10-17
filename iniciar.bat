@echo off
rem Abre a tela com o Python do ambiente da POC, a partir desta pasta. O "streamlit" do Anaconda
rem nao tem o docling nem as versoes de biblioteca que o projeto usa, e fora desta pasta o
rem Streamlit nao le o .streamlit\config.toml
cd /d "%~dp0"
"%USERPROFILE%\.venvs\subscricao-poc\Scripts\python.exe" -m streamlit run app.py %*
