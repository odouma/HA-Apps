FROM ghcr.io/home-assistant/base:latest

# Python + Flask + grafieken (matplotlib via apk, i.p.v. compileren via pip)
# + paho-mqtt voor apparaat-groepering in Home Assistant
# + websocket-client voor de statistics-websocket-API (langetermijndata,
#   in tegenstelling tot de REST-API die alleen de states-tabel benadert)
RUN apk add --no-cache python3 py3-pip py3-numpy py3-matplotlib \
    && pip3 install --no-cache-dir --break-system-packages \
       flask requests "paho-mqtt<2.0.0" websocket-client

# App-bestanden kopiëren
COPY app /app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /app

CMD [ "/run.sh" ]
