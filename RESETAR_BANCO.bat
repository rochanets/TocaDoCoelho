@echo off
chcp 65001 >nul
cls

echo.
echo ========================================================
echo   RESETAR BANCO DE DADOS - TOCA DO COELHO
echo ========================================================
echo.
echo Isso vai deletar o banco de dados antigo e criar um novo.
echo Todos os dados serão perdidos!
echo.
pause

python RESETAR_BANCO.py

echo.
pause
