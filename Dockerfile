FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TONPRICES_DB=/data/ton-prices.sqlite3
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY tonprices ./tonprices
EXPOSE 8087
CMD ["python", "-m", "uvicorn", "tonprices.app:app", "--host", "0.0.0.0", "--port", "8087"]
