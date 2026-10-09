FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install --no-install-recommends --yes tor \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/lib/tor/imageboard \
    && chown -R debian-tor:debian-tor /var/lib/tor \
    && chmod 0700 /var/lib/tor /var/lib/tor/imageboard

COPY torrc /etc/tor/torrc

USER debian-tor

CMD ["tor", "-f", "/etc/tor/torrc"]
