FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py .
COPY app ./app

# Pre-download the Smart Turn v3 weights (~9MB) so the first live call
# never pays for a HuggingFace download on the media path (Hush models
# ship inside its wheel and need no warmup).
RUN python -c "from smart_turn_livekit import SmartTurnDetector; SmartTurnDetector()"

CMD ["python", "agent.py"]
