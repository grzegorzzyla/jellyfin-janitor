FROM debian:bookworm-slim
ARG DOVI_VERSION=2.3.4
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends ffmpeg mkvtoolnix python3 curl ca-certificates tzdata \
 && curl -fsSL "https://github.com/quietvoid/dovi_tool/releases/download/${DOVI_VERSION}/dovi_tool-${DOVI_VERSION}-x86_64-unknown-linux-musl.tar.gz" \
    | tar -xz -C /usr/local/bin \
 && rm -rf /var/lib/apt/lists/* \
 && dovi_tool --version && mkvmerge --version
COPY *.py index.html /app/
EXPOSE 8080
CMD ["python3", "-u", "/app/app.py"]
