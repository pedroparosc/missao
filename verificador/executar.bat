@echo off
rem Abre o Verificador de Prestacao de Contas no navegador.
rem O ambiente virtual fica fora do OneDrive para nao sincronizar milhares de arquivos.
set VENV=%LOCALAPPDATA%\verificador-prestacao\venv
cd /d "%~dp0"
if not exist "%VENV%\Scripts\python.exe" (
    echo Criando ambiente Python pela primeira vez...
    python -m venv "%VENV%" || (echo Python nao encontrado. Instale em https://www.python.org & pause & exit /b 1)
)
"%VENV%\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
"%VENV%\Scripts\python.exe" -m streamlit run app.py --browser.gatherUsageStats false
pause
