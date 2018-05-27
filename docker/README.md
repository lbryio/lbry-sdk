## Speech-As-A-Container

I'll document a bit of this later but for now you may look over ```docker-compose.yml``` and then modify any environment variables you feel the need to.

#### Invocation

```docker-compose up -d```

#### Executing commands

To list containers on the host execute `docker ps -a` then run `docker exec CONTAINERNAME lbrynet-cli commands`

#### Docker Directory

This directory is in case we need to expand the functionality of this container at some point in the future.
