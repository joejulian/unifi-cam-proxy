History
-------

0.3.6
+++++

* Add GitHub Actions CI coverage for linting and the requirement-level test suite.
* Raise the supported Python floor to 3.12.4 to match current runtime dependencies.
* Refresh runtime dependencies, including the Protect client library and camera integrations.
* Fix Protect token generation cleanup when the API client fails before a session is created.

0.3.5
+++++

* Improve RTSP metadata handling so adopted cameras preserve Protect RTSP aliases
  and report per-stream dimensions more accurately.
* Publish release images for the architectures used by the cluster (`amd64`,
  `arm64`) directly to `ghcr.io/joejulian/unifi-cam-proxy`.
* Test protected `main` and `v*` refs for release publishing behavior.
