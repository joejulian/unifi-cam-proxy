History
-------

0.3.3
+++++

* Improve RTSP metadata handling so adopted cameras preserve Protect RTSP aliases
  and report per-stream dimensions more accurately.
* Publish release images for the architectures used by the cluster (`amd64`,
  `arm64`) directly to `ghcr.io/joejulian/container-images/unifi-cam-proxy`.
* Use the repository automation token for GHCR publishing so releases can push
  to the shared `container-images` package namespace.
