FROM python:3.12-slim

WORKDIR /app

# Install nginx and supervisor
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install backend dependencies
COPY backend_requirements.txt .
RUN pip install --no-cache-dir -r backend_requirements.txt

# Copy backend code and data
COPY backend.py .
COPY ttp_analyzer.py .
COPY markdown_generator.py .
COPY enterprise_attack_v17.1_ids.json .

# Copy nginx config
COPY nginx.conf /etc/nginx/nginx.conf

# Copy static frontend files
COPY index.html /usr/share/nginx/html/
COPY styles.css /usr/share/nginx/html/
COPY main.js /usr/share/nginx/html/

# Copy supervisor config
COPY supervisord.conf /etc/supervisord.conf

# Expose port
EXPOSE 80

# Run supervisor to manage nginx + backend
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisord.conf"]

