FROM ubuntu:20.04
COPY lbrynet /bin
RUN lbrynet --version
ENTRYPOINT ["lbrynet"]
CMD ["start", "--full-node"]
