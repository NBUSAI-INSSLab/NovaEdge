@echo off
chcp 65001 >nul
REM NovaEdge 一键启动（开发环境，Windows）
REM 前置条件：backend 依赖已安装（pip install -r requirements.txt）
REM           frontend 已构建（npm run build）或另行 npm run dev

setlocal
cd /d "%~dp0"

echo [1/2] 初始化数据库（首次运行会建表并写入演示数据与设备凭证）...
python init_db.py --seed

echo.
echo [2/2] 启动平台服务  http://127.0.0.1:5000
echo       控制台账号:  admin / admin123（管理员）
echo 按 Ctrl+C 停止
echo.
python run.py
endlocal
