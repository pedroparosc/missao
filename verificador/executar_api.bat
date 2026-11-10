@echo off
rem Inicia a API (backend) do Verificador em http://localhost:8000  (documentacao em /docs).
rem Usa o mesmo ambiente virtual do executar.bat, fora do OneDrive.
rem Para o frontend usar a API, rode antes do executar.bat:  set VERIFICADOR_API_URL=http://localhost:8000
set VENV=%LOCALAPPDATA%\verificador-prestacao\venv
cd /d "%~dp0"
if not exist "%VENV%\Scripts\python.exe" (
    echo Criando ambiente Python pela primeira vez...
    python -m venv "%VENV%" || (echo Python nao encontrado. Instale em https://www.python.org & pause & exit /b 1)
)
"%VENV%\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
echo API em http://localhost:8000/docs  (Ctrl+C para parar)
"%VENV%\Scripts\python.exe" -m uvicorn api.main:app --port 8000
pause
