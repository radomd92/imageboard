FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install --no-install-recommends --yes nginx-full \
    && rm -rf /var/lib/apt/lists/*

COPY nginx.conf /etc/nginx/nginx.conf
COPY onion.conf /etc/nginx/conf.d/onion.conf
COPY account_locations.conf /etc/nginx/account_locations.conf
COPY account_proxy.conf /etc/nginx/account_proxy.conf

EXPOSE 8443

CMD ["nginx", "-g", "daemon off;"]
