FROM python:3.12-slim
RUN pip install --no-cache-dir asyncua==1.1.5 aiohttp==3.10.10 anthropic==2.12.0 aiomqtt==2.3.0
WORKDIR /app
COPY *.py ./
USER 1000:1000
EXPOSE 8090
CMD ["python", "-u", "gateway.py"]
