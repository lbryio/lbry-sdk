FROM ubuntu:20.04
COPY lbrynet /bin
ENTRYPOINT ["lbrynet", "start", "--full-node"]
