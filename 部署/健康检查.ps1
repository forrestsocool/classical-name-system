param(
    [string]$地址 = "http://127.0.0.1:8000"
)

$文本 = & curl.exe --fail --silent --show-error --noproxy "*" --max-time 5 "$地址/api/ready"
if ($LASTEXITCODE -ne 0) {
    throw "无法连接服务：$地址"
}
$结果 = $文本 | ConvertFrom-Json
if ($结果.状态 -ne "就绪") {
    throw "服务未就绪"
}

Write-Output "服务就绪：$地址"
