# Historical reference only. Maintained deployment/tests require a native host.
ARG UBUNTU_IMAGE=ubuntu:26.04@sha256:f144425ff09be612d6d9ad965196e9cdc23dae1f42110a8a11a3e9a8198759f7
FROM ${UBUNTU_IMAGE}
ENV container=docker
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y systemd systemd-sysv sudo python3 python3-venv git ca-certificates ripgrep && rm -rf /var/lib/apt/lists/*
WORKDIR /project
COPY requirements-dev.txt /project/
RUN python3 -m venv /opt/check-venv && /opt/check-venv/bin/python -m pip install --no-cache-dir -r requirements-dev.txt
COPY ansible.cfg .ansible-lint .yamllint pyproject.toml /project/
COPY playbooks /project/playbooks
COPY roles /project/roles
COPY inventory/hosts.example.yml /project/inventory/hosts.example.yml
COPY scripts /project/scripts
COPY tests /project/tests
ENV PATH=/opt/check-venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
