@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Preparando o MAGISTERIA pela primeira vez...
  python -m venv .venv
  if errorlevel 1 goto :erro
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :erro
)

".venv\Scripts\python.exe" -c "import PIL, pptx" >nul 2>&1
if errorlevel 1 (
  echo Atualizando os recursos de roteiro e apresentacao...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :erro
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo.
  echo Configure sua chave OPENAI_API_KEY no arquivo .env e execute novamente.
  start "" notepad ".env"
  pause
  exit /b 1
)

echo Iniciando o MAGISTERIA e atualizando a base documental...
echo O navegador sera aberto assim que tudo estiver pronto.
".venv\Scripts\python.exe" launcher.py
exit /b

:erro
echo.
echo Nao foi possivel preparar o aplicativo. Verifique sua conexao e tente novamente.
pause
exit /b 1
