FROM postgres:14.0

ENV POSTGRES_PASSWORD postgres

COPY ./ddl.sql /docker-entrypoint-initdb.d/

RUN apt-get update && \
    apt-get clean && \
    rm -fr /var/lib/apt/lists/*