# nginx for the "The Heroes' Journey" web build.
#
# The stock `nginx:alpine` image has `gzip_static` but no brotli module, and the
# Alpine brotli module is built against Alpine's own nginx (ABI-incompatible
# with the nginx.org build in `nginx:alpine`).  So build from plain Alpine and
# take both nginx and the matching brotli module from the Alpine repos.
#
# Nothing is COPYed in: web.conf and build/ are bind-mounted by docker-compose.
FROM alpine:3.23

RUN apk add --no-cache nginx nginx-mod-http-brotli \
    && rm -f /etc/nginx/http.d/default.conf \
    && ln -sf /dev/stdout /var/log/nginx/access.log \
    && ln -sf /dev/stderr /var/log/nginx/error.log

# /etc/nginx/nginx.conf pulls in /etc/nginx/modules/*.conf (which load_module's
# brotli) and /etc/nginx/http.d/*.conf (where web.conf gets mounted).
EXPOSE 8070
STOPSIGNAL SIGQUIT
CMD ["nginx", "-g", "daemon off;"]
