@echo off
chcp 65001 >nul
cd /d "%~dp0"
if "%API_PROJECT%"=="" set API_PROJECT=shopping
echo === %API_PROJECT% 接口自动化测试（项目目录：projects\%API_PROJECT%） ===
D:\python\python.exe -m pytest -o testpaths=projects/%API_PROJECT%/testcases %*
echo.
echo 报告: %~dp0reports\report.html
