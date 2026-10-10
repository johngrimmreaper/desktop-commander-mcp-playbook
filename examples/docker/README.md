# Historical Docker reference

The earlier test environment used a disposable systemd container to exercise
package downloads/builds without installing on the host. The Dockerfile is
retained as an example of that test arrangement, with the Ubuntu 26.04 image
digest observed during the earlier pull.

The project now deploys and validates directly on native Ubuntu 26.04.
Ansible rejects container targets, and the native host test scripts refuse to
run inside containers. This example is not a deployment path or a supported
integration test target. It has no relationship to daemon startup or operation.

Use the root README for current native installation and validation commands.
