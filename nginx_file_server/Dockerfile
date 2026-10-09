FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install --no-install-recommends --yes nginx-full libnginx-mod-http-image-filter \
    && rm -rf /var/lib/apt/lists/*

COPY nginx.conf /etc/nginx/nginx.conf
COPY onion.conf /etc/nginx/conf.d/onion.conf

EXPOSE 8443

CMD ["nginx", "-g", "daemon off;"]
