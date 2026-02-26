@echo off
chcp 65001 > nul
echo 正在启动 N.E.K.O. 双服务器环境...

:: 切换到脚本所在的目录
cd /d "%~dp0"

:: 启动主服务器 (Main Server)
start "NEKO Main Server" cmd /k "uv run python main_server.py"

:: 等待 2 秒
timeout /t 2 > nul

:: 启动记忆服务器 (Memory Server)
start "NEKO Memory Server" cmd /k "uv run python memory_server.py"

echo 服务器指令已下达。
pause