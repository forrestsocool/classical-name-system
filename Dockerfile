FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    起名数据库路径=/app/构建产物/起名系统.sqlite3

WORKDIR /app

# 安装依赖
COPY 后端/requirements.txt /app/后端/requirements.txt
RUN pip install --no-cache-dir -r /app/后端/requirements.txt

# 复制项目运行所需文件
COPY 前端/ /app/前端/
COPY 后端/ /app/后端/
COPY 构建产物/ /app/构建产物/
COPY 脚本/ /app/脚本/
COPY 资料配置/ /app/资料配置/
COPY 古籍与东亚年号参考资料/ /app/古籍与东亚年号参考资料/
COPY 公安部姓名报告参考资料/ /app/公安部姓名报告参考资料/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ready')" || exit 1

CMD ["python", "-m", "uvicorn", "后端.起名服务:应用", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
