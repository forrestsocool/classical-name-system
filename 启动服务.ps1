param(
    [string]$绑定地址 = "127.0.0.1",
    [int]$端口 = 8000,
    [int]$工作进程 = 1
)

Set-Location -LiteralPath $PSScriptRoot

if (-not $env:起名管理密钥) {
    throw "请先设置环境变量：起名管理密钥"
}

if ($env:起名管理密钥.Length -lt 16) {
    throw "起名管理密钥至少需要16个字符"
}

if ($工作进程 -ne 1) {
    throw "SQLite 模式必须使用单个工作进程"
}

python .\脚本\部署检查.py
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

python -m uvicorn 后端.起名服务:应用 --host $绑定地址 --port $端口 --workers $工作进程
