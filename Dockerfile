## Base Image
FROM ubuntu:18.04
MAINTAINER chamunks [at] gmail [dot] com

RUN apt-get update && apt-get -y install unzip
# RUN mkdir -pv /app && chown 1000:1000 /app
RUN adduser lbrynet --gecos GECOS --shell /bin/bash/ --disabled-password --home /app/

## Add lbrynet
ADD https://lbry.io/get/lbrynet.linux.zip /app/lbrynet.linux.zip
RUN unzip /app/lbrynet.linux.zip -d /app/ && \
    rm /app/lbrynet.linux.zip && \
    chown -Rv lbrynet:lbrynet /app

## Install into PATH
RUN mv /app/lbrynet-* /bin/ && \
    ls -lAh /bin/

## Daemon port
EXPOSE 4444
# ## Peer port
# EXPOSE 3333
## Wallet port
EXPOSE 50001

## Undocumented ports that exist in conf.py
## API port
# EXPOSE 5279
# ## Reflector port
# EXPOSE 5566

# VOLUME /app/.local/share/lbry/lbryum/wallets
# VOLUME /app/.local/
## Not sure where this is going to be.
# VOLUME /app/.config/conf.py
# VOLUME /app/Downloads/

## Never run container processes as root
USER lbrynet
## Run on container launch
CMD ["lbrynet-daemon"]

## Setting this entrypoint should mean that you can `docker exec lbrynet commands`
## and you should be able to control the daemon's CLI this way.  There is an
## alternative method we could use here where we have an entrypoint shell script which could be a bit smarter.
# ENTRYPOINT ["lbrynet-cli"]
