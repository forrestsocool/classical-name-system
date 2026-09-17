param(
    [string]$绑定地址 = "127.0.0.1",
    [int]$端口 = 8000,
    [int]$工作进程 = 2
)
Set-Location -LiteralPath $PSScriptRoot
if (-not $env:DATABASE_URL) { throw "请设置 PostgreSQL DATABASE_URL 并先运行迁移" }
if (-not $env:起名管理密钥 -or $env:起名管理密钥.Length -lt 16) { throw "管理密钥至少需要16位ASCII字符" }
if (-not $env:GATEWAY_SECRET -or $env:GATEWAY_SECRET.Length -lt 32) { throw "GATEWAY_SECRET 至少需要32位随机ASCII字符" }
if (-not $env:WECHAT_APP_ID) { throw "请设置 WECHAT_APP_ID" }
python -m uvicorn 后端.小程序服务:应用 --host $绑定地址 --port $端口 --workers $工作进程
