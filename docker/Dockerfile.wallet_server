FROM debian:10-slim

ARG user=lbry
ARG db_dir=/database
ARG projects_dir=/home/$user

ARG DOCKER_TAG
ARG DOCKER_COMMIT=docker
ENV DOCKER_TAG=$DOCKER_TAG DOCKER_COMMIT=$DOCKER_COMMIT

RUN apt-get update && \
    apt-get -y --no-install-recommends install \
      wget \
      tar unzip \
      build-essential \
      automake libtool \
      pkg-config \
      libleveldb-dev \
      python3.7 \
      python3-dev \
      python3-pip \
      python3-wheel \
      python3-cffi \
      python3-setuptools && \
    update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1 && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd -g 999 $user && useradd -m -u 999 -g $user $user
RUN mkdir -p $db_dir
RUN chown -R $user:$user $db_dir

COPY . $projects_dir
RUN chown -R $user:$user $projects_dir

USER $user
WORKDIR $projects_dir

RUN pip install uvloop
RUN make install
RUN python3 docker/set_build.py
RUN rm ~/.cache -rf

# entry point
ARG host=0.0.0.0
ARG tcp_port=50001
ARG daemon_url=http://lbry:lbry@localhost:9245/
VOLUME $db_dir
ENV TCP_PORT=$tcp_port
ENV HOST=$host
ENV DAEMON_URL=$daemon_url
ENV DB_DIRECTORY=$db_dir
ENV MAX_SESSIONS=1000000000
ENV MAX_SEND=1000000000000000000
ENV EVENT_LOOP_POLICY=uvloop
COPY ./docker/wallet_server_entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
