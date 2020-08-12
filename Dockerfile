FROM ubuntu:20.04

ENV DEBIAN_FRONTEND noninteractive
RUN apt-get update && \
    apt-get -y --no-install-recommends install \
      wget git \
      tar unzip \
      libpq-dev pkg-config \
      build-essential \
      python3 \
      python3-dev \
      python3-pip \
      python3-wheel \
      python3-setuptools && \
    update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1 && \
    rm -rf /var/lib/apt/lists/*

VOLUME /data
VOLUME /lbrycrd
RUN mkdir /src
COPY lbry /src/lbry
COPY setup.py /src/setup.py
COPY README.md /src/README.md
COPY settings.yml /data/settings.yml
WORKDIR /src
RUN pip install --no-cache-dir -e .[postgres]

ENTRYPOINT ["lbrynet", "start", "--full-node", "--data-dir=/data", "--lbrycrd-dir=/lbrycrd"]
