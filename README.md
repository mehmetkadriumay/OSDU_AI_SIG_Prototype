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

`spark-iceberg` is built from `spark-iceberg/Dockerfile` on top of `tabulario/spark-iceberg`. It:

- pins `prettytable<3.12` so the `%sql` magic works,
- adds the Java 17 `--add-opens` flags to the Java (IJava) kernel so Spark can start there,
- replaces the bundled notebooks with the copies in `spark-iceberg/notebooks/`, fixed for SeaweedFS (endpoint, path-style access, namespace bugs, DuckDB `%sql` setup).

`rest` is pinned to `apache/iceberg-rest-fixture:1.8.1`: newer images reject Spark's `%1F` namespace separator.

## Repo layout

```
docker-compose.yml        # the stack
seaweedfs/s3.json         # SeaweedFS S3 identity (admin / password)
setup.sh                  # builds spark/spark-defaults.conf pointing at seaweedfs:9000
spark-iceberg/Dockerfile  # spark-iceberg image with the fixes below
spark-iceberg/notebooks/  # bundled Iceberg/PyIceberg notebooks, fixed for this stack
spark-iceberg/patch_java_kernel.py
```

## Step 0 – Prerequisites

Docker and Docker Compose, or Podman with `docker-compose` (`alias docker=podman` or a `docker` symlink to `podman`; on macOS run `podman machine start` first). Clone the repo:

```bash
git clone https://github.com/mehmetkadriumay/OSDU_AI_SIG_Prototype.git
cd OSDU_AI_SIG_Prototype
```

### Using Podman instead of Docker (macOS)

1. Make `docker` resolve to Podman: `alias docker=podman`, or a symlink such as `sudo ln -s "$(which podman)" /usr/local/bin/docker`. If `podman` itself isn't found after installing the official `.pkg`, add `/opt/podman/bin` to your `PATH`.
2. Give the VM enough memory. The default 2 GB is too little for loading the taxi data into pandas: the Jupyter kernel dies with "Kernel Restarting".
   ```bash
   podman machine init --memory 8192 --cpus 4    # or, for an existing VM:
   podman machine stop && podman machine set --memory 8192 --cpus 4 && podman machine start
   ```
   If `podman machine start` fails with `exec: "krunkit": executable file not found in $PATH`, put `/opt/podman/bin` on your `PATH` (`.pkg` install) or run `brew tap slp/krunkit && brew install krunkit` (Homebrew install).
3. Point `docker-compose` at Podman's socket instead of Docker Desktop's:
   ```bash
   export DOCKER_HOST="unix://$(podman machine inspect --format '{{.ConnectionInfo.PodmanSocket.Path}}')"
   ```
   or run `sudo podman-mac-helper install` once and restart the machine.
4. If you previously had Docker Desktop, remove `"credsStore": "desktop"` from `~/.docker/config.json`.

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
docker compose up -d --build
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

## Querying PyIceberg data with DuckDB (`%sql`) in Jupyter

The `PyIceberg - Getting Started` notebook loads a table into a pandas `df` and queries it with `%sql`. Two things make this work reliably:

```python
tbl = cat.load_table("default.taxis")
sc = tbl.scan(row_filter="tpep_pickup_datetime >= '2021-05-01T00:00:00.000000'")
df = sc.to_arrow().to_pandas()          # needs a VM with enough memory, or add limit=... to scan()

import duckdb
conn = duckdb.connect()
conn.execute("CREATE OR REPLACE TABLE df AS SELECT * FROM df")   # real table, visible to %sql

%load_ext sql
%config SqlMagic.autopandas = True
%config SqlMagic.feedback = False
%config SqlMagic.displaycon = False
%sql conn --alias duckdb                # instead of %sql duckdb:///:memory:
```

```sql
%sql SELECT * FROM df LIMIT 20
```

- Use a real `CREATE TABLE`, not `conn.register(...)`: jupysql runs queries on a cursor, and cursors can't see registered (temporary) views.
- Don't also run `%sql duckdb:///:memory:`. It creates a second, empty database and makes it the active connection. Check with `%sql --connections` (the active one has `*`).
- If the table changes, rerun the `CREATE OR REPLACE TABLE` line.

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
| Jupyter "Kernel Restarting" on `sc.to_arrow().to_pandas()` | Out of memory. Raise the Podman VM memory (see *Using Podman*) or add `limit=` / `selected_fields=` to `tbl.scan(...)`. |
| `%sql`: `Catalog Error: Table with name df does not exist!` | See *Querying PyIceberg data with DuckDB*: create a real DuckDB table and make sure the right connection is active. |
| `%sql`: `KeyError: 'DEFAULT'` | jupysql vs. prettytable ≥ 3.12. Rebuild with `docker compose up -d --build`, or in the notebook `%pip install "prettytable<3.12"` and restart the kernel, or `%config SqlMagic.style = "_DEPRECATED_DEFAULT"`. |
| `failed to connect to the docker API at unix:///Users/.../.docker/run/docker.sock` (Podman) | `docker-compose` is looking for Docker Desktop. Set `DOCKER_HOST` to the Podman socket (see *Using Podman*). |
| `podman machine start`: `exec: "krunkit": executable file not found` | Add `/opt/podman/bin` to `PATH`, or `brew tap slp/krunkit && brew install krunkit`. |
| `BadRequestException: Malformed request ... "Suspicious Path Character" ... nyc%1Ftaxis` on `.snapshots`, `.files`, `.history`, `.refs` or branches | The REST catalog image is too new. Keep `rest` pinned to `apache/iceberg-rest-fixture:1.8.1`. |
| `EOFException: Reached the end of stream with ... bytes left to read` | Objects were truncated on upload by the AWS SDK's default checksums. Keep `AWS_REQUEST_CHECKSUM_CALCULATION` / `AWS_RESPONSE_CHECKSUM_VALIDATION=when_required` in the compose file, then rerun the notebook so the data is rewritten. |
| Java notebook: `cannot access class sun.nio.ch.DirectBuffer` | The Java kernel is missing the `--add-opens` flags. Rebuild with `docker compose up -d --build`. |
| `Namespace nyc does not exist` | Run a notebook that creates `nyc` first (e.g. `Iceberg - Getting Started`). The fixed notebooks create it themselves. |
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
