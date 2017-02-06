# Change Log
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/) with
regard to the json-rpc api.  As we're currently pre-1.0 release, we
can and probably will change functionality and break backwards compatability
at anytime.

## [Unreleased]

## [0.8.1] - 2017-02-01
### Changed
 * reflect all the blobs in a stream
 * change command line flags so that the more common usage is the default
 * change daemon function signatures to include names arguments
### Fixed
 * disable verbose twisted logs
 * improved wallet balance calculations
 * fix block too deep error

## [0.8.0] - 2017-01-24
### Changed
 * renamed api endpoints
 * improved command line user experience
 * integrate twisted logging with python logging
 * Updated READMEs
### Fixed
 * Fixed bug where ConnectionManager wasn't being stopped
 * Fixed: #343
 * Stop hanging if github is down
 * paths for debian package have been updated to be correct
 * improved output of the publish command
