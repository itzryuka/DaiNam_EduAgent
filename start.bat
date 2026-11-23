@echo off
rem Nhấp đúp file này để khởi động toàn bộ EduAgent (MySQL, CSDL, mô hình, backend, giao diện).
rem Tham số thêm được chuyển cho start.py, ví dụ:  start.bat --check   hoặc   start.bat --train
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
    echo Chua co moi truong ao .venv, dang tao va cai thu vien (lan dau mat vai phut^)...
    python -m venv .venv || (echo Khong tim thay Python. Cai Python 3.12+ tu python.org roi chay lai. & pause & exit /b 1)
    ".venv\Scripts\python.exe" -m pip install -r ml\requirements.txt -r backend\requirements.txt
)

".venv\Scripts\python.exe" start.py %*
echo.
pause
