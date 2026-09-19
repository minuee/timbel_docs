FROM minio/minio:latest

COPY timbloInit.sh /usr/local/bin/timbloInit.sh
RUN chmod +x /usr/local/bin/timbloInit.sh

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["server", "/data"]
