@echo off
REM DiscordChatExporter.Cli Windows Launcher / Simulator
set BIN_DIR=%~dp0
python "%BIN_DIR%cli_runner.py" %*
