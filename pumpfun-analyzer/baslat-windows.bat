@echo off
setlocal

if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo .env dosyasi .env.example dosyasindan olusturuldu.
  ) else (
    echo HATA: .env.example bulunamadi.
    pause
    exit /b 1
  )
)

echo Altay Analysis Bot baslatiliyor...
docker compose up --build
pause
