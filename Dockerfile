FROM ubuntu:20.04
COPY ./dist/lbrynet /bin
ENTRYPOINT ["lbrynet", "start", "--full-node"]
