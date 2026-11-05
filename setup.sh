#!/usr/bin/env sh
# Prepares the Spark config so the demo catalog talks to SeaweedFS (path-style, no minio aliases).
set -e
mkdir -p spark warehouse notebooks

# 1. Copy the image's own spark-defaults.conf
docker run --rm --entrypoint cat tabulario/spark-iceberg \
  /opt/spark/conf/spark-defaults.conf > spark/spark-defaults.conf

# 2. Point the demo catalog at SeaweedFS
sed -i.bak 's#http://minio:9000#http://seaweedfs:9000#g' spark/spark-defaults.conf

# 3. Make sure endpoint + path-style access are set
grep -q "catalog.demo.s3.endpoint" spark/spark-defaults.conf || \
  echo "spark.sql.catalog.demo.s3.endpoint            http://seaweedfs:9000" >> spark/spark-defaults.conf
sed -i.bak '/catalog.demo.s3.path-style-access/d' spark/spark-defaults.conf
echo "spark.sql.catalog.demo.s3.path-style-access   true" >> spark/spark-defaults.conf

echo "--- demo catalog settings ---"
grep "catalog.demo" spark/spark-defaults.conf
