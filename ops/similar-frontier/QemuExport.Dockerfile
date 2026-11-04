FROM ubuntu@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852 AS compiler
RUN sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates build-essential python3 python3-venv ninja-build meson \
        pkg-config libglib2.0-dev libfuse3-dev libzstd-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /source
COPY qemu-source-sha256.txt /source/checksums
RUN apt-get update \
    && apt-get source --download-only qemu=1:8.2.2+ds-0ubuntu1.18 \
    && sha256sum -c checksums \
    && dpkg-source -x qemu_8.2.2+ds-0ubuntu1.18.dsc \
    && useradd --create-home --uid 10001 builder \
    && mkdir /build \
    && chown -R builder:builder /source /build
COPY --chown=builder:builder qemu-sealed-export.patch /source/sealed.patch
USER builder
WORKDIR /source/qemu-8.2.2+ds
RUN patch --batch --fuzz=0 -p1 < /source/sealed.patch
WORKDIR /build
RUN /source/qemu-8.2.2+ds/configure --target-list= --disable-system --disable-user \
        --disable-guest-agent --disable-docs --disable-install-blobs --disable-werror \
        --enable-tools --enable-fuse --enable-zstd \
    && ninja -j2 storage-daemon/qemu-storage-daemon

FROM scratch
COPY --from=compiler /build/storage-daemon/qemu-storage-daemon /qemu-storage-daemon
COPY --from=compiler /source/qemu_8.2.2+ds-0ubuntu1.18.dsc /build-source/
COPY --from=compiler /source/qemu_8.2.2+ds-0ubuntu1.18.debian.tar.xz /build-source/
COPY --from=compiler /source/qemu_8.2.2+ds.orig.tar.xz /build-source/
COPY --from=compiler /source/checksums /build-source/qemu-source-sha256.txt
COPY --from=compiler /source/sealed.patch /build-source/qemu-sealed-export.patch
USER 65532:65532
