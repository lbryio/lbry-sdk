FROM ubuntu:20.04
COPY lbrynet /bin
RUN chmod +x /bin/lbrynet
ENTRYPOINT ["lbrynet"]
CMD ["start", "--full-node"]
