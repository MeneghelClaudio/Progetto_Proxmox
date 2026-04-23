FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf

# Static assets
COPY *.html   /usr/share/nginx/html/
COPY *.css    /usr/share/nginx/html/
COPY *.js     /usr/share/nginx/html/

EXPOSE 80
