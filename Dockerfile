# Use an official Python runtime as a parent image
# Version alignée sur la CI (.github/workflows/CI.yml) et l'environnement local.
FROM python:3.13-slim

# Bruit en moins dans les logs, pas de .pyc à écrire dans le conteneur.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code into the container at /app
COPY ./app /app/app

# A05 — Security Misconfiguration : ne pas exécuter l'application en root.
# Un utilisateur sans privilège limite la portée d'une exécution de code
# arbitraire dans le conteneur.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Port non privilégié : requis dès lors que le processus n'est plus root.
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"

# Command to run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
