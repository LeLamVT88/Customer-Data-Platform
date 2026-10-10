FROM eclipse-temurin:17.0.18_8-jre-jammy AS java_runtime

FROM apache/spark:3.5.8
USER root
# Iceberg 1.11 requires Java 17; the Spark base image contains Java 11.
COPY --from=java_runtime /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk
RUN pip3 install --no-cache-dir duckdb==1.5.6
ADD https://repo.maven.apache.org/maven2/org/apache/iceberg/iceberg-spark-runtime-3.5_2.12/1.11.0/iceberg-spark-runtime-3.5_2.12-1.11.0.jar /opt/spark/jars/
ADD https://repo.maven.apache.org/maven2/org/apache/iceberg/iceberg-aws-bundle/1.11.0/iceberg-aws-bundle-1.11.0.jar /opt/spark/jars/
ADD https://repo.maven.apache.org/maven2/org/postgresql/postgresql/42.7.8/postgresql-42.7.8.jar /opt/spark/jars/
RUN chmod 644 /opt/spark/jars/*.jar
WORKDIR /workspace
