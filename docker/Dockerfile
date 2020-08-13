FROM ubuntu:20.04
RUN ls
COPY lbrynet /bin
RUN /bin/ls
RUN lbrynet --version
ENTRYPOINT ["lbrynet"]
CMD ["start", "--full-node"]
