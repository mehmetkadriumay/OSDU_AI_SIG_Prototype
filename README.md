# Spark + Iceberg Quickstart with SeaweedFS

A variant of the official [Spark and Iceberg Quickstart](https://iceberg.apache.org/spark-quickstart/) that uses **SeaweedFS** as the S3-compatible object store instead of MinIO/RustFS.

Spark and the Iceberg REST catalog address SeaweedFS by its real hostname (`seaweedfs:9000`) using **path-style** S3 — no `minio` network aliases or virtual-host tricks.

> Status: prototype, not yet validated end-to-end. SeaweedFS flags may need adjusting for your SeaweedFS version.

## Architecture

| Service | Image | Role | Host ports |
|---|---|---|---|
| `spark-iceberg` | `tabulario/spark-iceberg` | Spark + Jupyter, `demo` catalog | 8888, 8080, 10000, 10001 |
| `rest` | `apache/iceberg-rest-fixture` | Iceberg REST catalog | 8181 |
| `seaweedfs` | `chrislusf/seaweedfs` | Master + volume + filer + S3 gateway | 9000 (S3), 9333 (master), 8889 (filer) |
| `create-bucket` | `curlimages/curl` | Creates the `warehouse` bucket | – |

## Repo layout

```
docker-compose.yml        # the stack
seaweedfs/s3.json         # SeaweedFS S3 identity (admin / password)
setup.sh                  # builds spark/spark-defaults.conf pointing at seaweedfs:9000
```

## Step 0 – Prerequisites

Docker and Docker Compose, or Podman with `docker-compose` (`alias docker=podman` or a `docker` symlink to `podman`; on macOS run `podman machine start` first). Clone the repo:

```bash
git clone https://github.com/mehmetkadriumay/OSDU_AI_SIG_Prototype.git
cd OSDU_AI_SIG_Prototype
```

## Step 1 – SeaweedFS S3 credentials

`seaweedfs/s3.json` defines the `admin` / `password` identity used by Spark and the REST catalog. Change both sides together if you change it.

## Step 2 – Prepare the Spark config

The `tabulario/spark-iceberg` image ships with its `demo` catalog pointed at `http://minio:9000`. `setup.sh` copies the image's own `spark-defaults.conf`, repoints it to `http://seaweedfs:9000` and enables path-style access:

```bash
chmod +x setup.sh
./setup.sh
```

Expected output includes:

```
spark.sql.catalog.demo.s3.endpoint            http://seaweedfs:9000
spark.sql.catalog.demo.s3.path-style-access   true
```

## Step 3 – Start the stack

```bash
docker compose up -d
docker logs -f create-bucket      # wait for: bucket 'warehouse' ready
```

## Step 4 – Open a Spark session

```bash
docker exec -it spark-iceberg spark-sql
# or
docker exec -it spark-iceberg pyspark
```

Or use Jupyter at http://localhost:8888. Confirm the endpoint:

```sql
SET spark.sql.catalog.demo.s3.endpoint;
SET spark.sql.catalog.demo.s3.path-style-access;
```

## Step 5 – Create a namespace and table

```sql
CREATE DATABASE IF NOT EXISTS demo.nyc;

CREATE TABLE demo.nyc.taxis (
  vendor_id bigint,
  trip_id bigint,
  trip_distance float,
  fare_amount double,
  store_and_fwd_flag string
) PARTITIONED BY (vendor_id);
```

## Step 6 – Write data

```sql
INSERT INTO demo.nyc.taxis VALUES
  (1, 1000371, 1.8, 15.32, 'N'),
  (2, 1000372, 2.5, 22.15, 'N'),
  (2, 1000373, 0.9,  9.01, 'N'),
  (1, 1000374, 8.4, 42.13, 'Y');
```

## Step 7 – Read data

```sql
SELECT * FROM demo.nyc.taxis;
```

## Step 8 – Verify the files landed in SeaweedFS

- Filer UI: http://localhost:8889/buckets/warehouse/ – look for `nyc/taxis/data/` and `nyc/taxis/metadata/`.
- From Spark:
  ```sql
  SELECT snapshot_id, operation FROM demo.nyc.taxis.snapshots;
  SELECT file_path FROM demo.nyc.taxis.files;
  ```
- From the host (AWS CLI):
  ```bash
  AWS_ACCESS_KEY_ID=admin AWS_SECRET_ACCESS_KEY=password AWS_REGION=us-east-1 \
  aws --endpoint-url http://localhost:9000 s3 ls s3://warehouse/ --recursive
  ```

## Step 9 – Try Iceberg features (optional)

```sql
ALTER TABLE demo.nyc.taxis ADD COLUMN tip double;
DELETE FROM demo.nyc.taxis WHERE trip_id = 1000373;
SELECT * FROM demo.nyc.taxis VERSION AS OF <first_snapshot_id>;  -- time travel
```

## Step 10 – Tear down

```bash
docker compose down        # keep data
docker compose down -v     # also delete SeaweedFS data
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `UnknownHostException: minio` | Spark isn't using the edited config. Re-run `./setup.sh`, check the mount, then `docker exec spark-iceberg grep endpoint /opt/spark/conf/spark-defaults.conf`. |
| `UnknownHostException: warehouse.seaweedfs` | Path-style access is off in Spark. Check `s3.path-style-access true` is in the config. |
| `CREATE DATABASE` works but `CREATE TABLE` fails | REST catalog can't reach SeaweedFS. Check `CATALOG_S3_ENDPOINT` / `CATALOG_S3_PATH__STYLE__ACCESS`; `docker logs iceberg-rest`. |
| `403 / SignatureDoesNotMatch` | Keys in `seaweedfs/s3.json` don't match the `AWS_*` env vars. |
| PyIceberg `curlCode: 6, Couldn't resolve host name` or `curlCode: 7, Couldn't connect to server` on `tbl.append(...)` | The notebook's PyIceberg catalog is still using the image default `http://minio:9000` (or `localhost`). The compose file overrides it with `PYICEBERG_CATALOG__DEFAULT__*` env vars; recreate the container (`docker compose up -d --force-recreate spark-iceberg`) and use `load_catalog("default")` without passing `s3.endpoint`, or pass `http://seaweedfs:9000`. |
| `docker-credential-desktop: executable file not found` (Podman) | Leftover Docker Desktop setting: remove `"credsStore": "desktop"` from `~/.docker/config.json`. |
| `create-bucket` keeps waiting | SeaweedFS didn't start: `docker logs seaweedfs`. |

One-off override without editing the config:

```bash
docker exec -it spark-iceberg spark-sql \
  --conf spark.sql.catalog.demo.s3.endpoint=http://seaweedfs:9000 \
  --conf spark.sql.catalog.demo.s3.path-style-access=true
```

## Credits

Based on the Apache Iceberg Spark quickstart (https://iceberg.apache.org/spark-quickstart/). Demo credentials only – do not use `admin` / `password` outside local testing.
