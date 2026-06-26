@echo off
chcp 65001 >nul
title 东营继续教育 - 打包程序

echo.
echo  ╔══════════════════════════════════════╗
echo  ║   正在打包，首次需要下载依赖，请稍候   ║
echo  ╚══════════════════════════════════════╝
echo.

:: 安装依赖
echo  [1/3] 安装依赖...
pip install pyinstaller selenium webdriver-manager -q
if errorlevel 1 (
    echo  ❌ pip 安装失败，请确认已安装 Python
    pause
    exit /b
)

:: 打包
echo  [2/3] 打包中...
pyinstaller --onefile --console --name "东营继续教育自动答题" main.py

:: 完成
echo.
echo  [3/3] 完成！
echo  生成文件位置：dist\东营继续教育自动答题.exe
echo.
pause
