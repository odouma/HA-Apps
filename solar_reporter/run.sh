#!/usr/bin/with-contenv bashio
bashio::log.info "Stroomtarieven addon wordt gestart..."
cd /app
exec python3 app.py
