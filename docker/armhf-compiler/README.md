# armhf-compiler

This container's goal is to make CI/CD easier for everyone, Travis CI, GitlabCI, Jenkins... Your desktop's docker equipped development environment.

## Example Usage

#### binfmt_misc register
This step sets up your docker daemon to support more container architectures.

Register `quemu-*-static` for all supported processors except the current one.
* `docker run --rm --privileged multiarch/qemu-user-static:register`

#### build the armhf bin
<!-- TODO: Process could be greatly sped up but keeping it simple for first release. -->
* `docker build --tag lbryio/lbrynet:armhf-compiler .`

#### export compiled bin to local /target
This containers sole purpose is to build and spit out the bin.
<!-- TODO: Fork this container base to begin work on LbryTV compiler to reduce build time on rpi -->
* `docker run --rm -ti -v $(pwd)/target:/target lbryio/lbrynet:armhf-compiler`


## Cleanup
If you're doing this on a machine you care to have restored to defaults this is the only host change we imposed so to revert the change you must execute the following docker command.

Same as above, but remove all registered `binfmt_misc` before
* `docker run --rm --privileged multiarch/qemu-user-static:register --reset`

