FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir pycryptodome
COPY miner_client.py fan_controller.py probe.py server.py ./
COPY static ./static
COPY miners.example.json ./
ENV SCLITE_WEBUI_HOST=0.0.0.0
ENV SCLITE_WEBUI_PORT=8790
EXPOSE 8790
CMD ["python", "-u", "server.py"]
