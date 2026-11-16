# Spark + Iceberg Quickstart with SeaweedFS

A variant of the official [Spark and Iceberg Quickstart](https://iceberg.apache.org/spark-quickstart/) that uses **SeaweedFS** as the S3-compatible object store instead of MinIO/RustFS.

Spark and the Iceberg REST catalog address SeaweedFS by its real hostname (`seaweedfs:9000`) using **path-style** S3 — no `minio` network aliases or virtual-host tricks.

> Status: local prototype. The WSLC path below has been verified with Spark SQL writes/reads, Iceberg metadata queries, PyIceberg reads/appends, and Jupyter SQL rendering against SeaweedFS.

## Architecture

| Service | Image | Role | Host ports |
|---|---|---|---|
| `spark-iceberg` | `tabulario/spark-iceberg` | Spark + Jupyter, `demo` catalog | 8888, 8080, 10000, 10001 |
| `rest` | `apache/iceberg-rest-fixture` | Iceberg REST catalog | 8181 |
| `seaweedfs` | `chrislusf/seaweedfs` | Master + volume + filer + S3 gateway | 9000 (S3), 9333 (master), 8889 (filer) |
| `create-bucket` | `curlimages/curl` | Creates the `warehouse` bucket | – |

`spark-iceberg` is built from `spark-iceberg/Dockerfile` on top of `tabulario/spark-iceberg`. It:

- sets Jupyter's SQL style to `_DEPRECATED_DEFAULT` so `%sql` works with the bundled prettytable version, without an extra package download,
- adds the Java 17 `--add-opens` flags to the Java (IJava) kernel so Spark can start there,
- replaces the bundled notebooks with the copies in `spark-iceberg/notebooks/`, fixed for SeaweedFS (endpoint, path-style access, namespace bugs).

`rest` is pinned to `apache/iceberg-rest-fixture:1.8.1`: newer images reject Spark's `%1F` namespace separator.

## Repo layout

```
docker-compose.yml        # the stack
seaweedfs/s3.json         # SeaweedFS S3 identity (admin / password)
setup.sh                  # builds spark/spark-defaults.conf pointing at seaweedfs:9000
setup-wslc.ps1            # Windows WSLC startup, status, and shutdown (no Docker engine)
notebooks/                # your saved notebooks, SQL, loader, reference workbook, and offline wheels
spark-iceberg/Dockerfile  # spark-iceberg image with the fixes below
spark-iceberg/notebooks/  # bundled Iceberg/PyIceberg notebooks, fixed for this stack
spark-iceberg/patch_java_kernel.py
```

## Windows: run with WSLC instead of Docker

WSLC is the **Windows Subsystem for Linux Container CLI** (`wslc.exe`), not a command inside an Ubuntu distribution. This path uses WSLC directly: Docker Desktop, the Docker engine, Docker Compose, and `setup.sh` are not needed. It still uses the existing container images and Dockerfile.

### Prerequisites

- Windows with WSL and a WSLC-enabled WSL installation. Confirm `wslc --help` and `wslc info` work in PowerShell; having `wsl.exe` alone is not sufficient.
- Git and internet access to pull the images. Allow roughly 8 GB of memory for the stack.
- Available localhost ports: 8888, 8080, 10000, 10001, 8181, 9000, 9333, and 8889. Stop any previous instance of this stack first; the script does not stop unrelated containers.

### Start from PowerShell

```powershell
git clone https://github.com/mehmetkadriumay/OSDU_AI_SIG_Prototype.git
Set-Location .\OSDU_AI_SIG_Prototype
.\setup-wslc.ps1
```

If PowerShell blocks the script under your execution policy, and your organization's policy permits it, run it with a process-only override:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup-wslc.ps1
```

The script builds the Spark image with `wslc build`, generates the Spark configuration, creates the `osdu-iceberg-net` network and `osdu-seaweed-data` volume, starts SeaweedFS, creates the `warehouse` bucket, and starts the REST catalog and Spark/Jupyter. It waits for readiness before reporting success. Re-running it reuses existing stack containers and starts stopped ones.

Open:

| Service | URL |
|---|---|
| Jupyter notebooks | http://localhost:8888 |
| Your saved notebooks | http://localhost:8888/tree/notebooks |
| Spark history UI | http://localhost:8080 |
| Iceberg REST configuration | http://localhost:8181/v1/config |
| SeaweedFS filer | http://localhost:8889/buckets/warehouse/ |
| SeaweedFS master | http://localhost:9333 |

Ports are bound to loopback only. These images and demo credentials are for local testing, not a secured production deployment.

### Run the SQL example

```powershell
wslc exec -it osdu-spark-iceberg spark-sql
# Or start a Python session:
wslc exec -it osdu-spark-iceberg pyspark
```

Run the SQL in **Steps 5–9** below, or open a bundled notebook in Jupyter. The internal endpoints remain `http://seaweedfs:9000` and `http://rest:8181`; do not replace them with `localhost` inside containers.

### Status, logs, and shutdown

```powershell
.\setup-wslc.ps1 status
wslc logs --tail 50 osdu-seaweedfs
wslc logs --tail 50 osdu-iceberg-rest
wslc logs --tail 50 osdu-spark-iceberg

# Remove only this stack's containers; preserve its data and network:
.\setup-wslc.ps1 down

# Start again (also rebuilds the image):
.\setup-wslc.ps1 up
```

SeaweedFS objects persist in the WSLC volume `osdu-seaweed-data`. Local `warehouse` and `notebooks` folders are bind-mounted just as in Compose; save your own notebooks in Jupyter's `notebooks` subfolder to retain them. The REST fixture is not configured with durable catalog storage: restarting it can lose table registrations even though the S3 objects remain. This is a disposable quickstart, not a durable catalog deployment.

### Save notebooks to GitHub and restore on deployment

The repository's `notebooks` directory contains:

- `Create OSDU Tables.ipynb` and its `osdu_well_wellbore_iceberg.sql` input.
- `load_iceberg_reference_data.ipynb`, its Python loader, `AllReferenceValues.iceberg.xlsx`, and offline packages in `wheels`.
- `Load Reference Data into Iceberg Tables.ipynb` (an empty notebook exported as-is).

Both WSLC and Compose mount this directory at `/home/iceberg/notebooks/notebooks`. After cloning or pulling the repository, startup makes these files available automatically at http://localhost:8888/tree/notebooks; no manual upload or notebook execution is performed. Changes saved in that Jupyter folder are written directly to the repository on Windows and survive container recreation. Keep companion files in that same folder so relative paths resolve.

The OSDU notebooks expect an Iceberg-enabled PySpark session with a catalog named `osdu_iceberg`; the bundled quickstart config names its catalog `demo`. Configure your session accordingly before running the OSDU notebooks, as described in the SQL file's prerequisites. Reference loading requires your deployment's ACL/legal settings and retains source attribution; review applicable data licenses before redistribution.

To export another notebook that was saved at the container's top level, run this from the repository directory in PowerShell (save it in Jupyter first):

```powershell
wslc cp 'osdu-spark-iceberg:/home/iceberg/notebooks/My Notebook.ipynb' .\notebooks\
```

The original is left untouched. Open the exported copy under Jupyter's `notebooks` folder for future edits. Before publishing, clear saved outputs in Jupyter and check notebook code and companion files for credentials or private data. Checkpoint/cache directories are ignored, but notebook files and their inputs are tracked:

```powershell
git add -- notebooks
git diff --cached --stat
git commit -m "Save notebooks and companion files"
git pull --rebase
git push
```

For future deployments, run `git pull` before `.\setup-wslc.ps1 up`. The saved notebooks are bind-mounted from the checkout rather than baked into the image, so they also update in an already running container. Back up or commit local notebook edits before pulling.

After changing the Dockerfile, bundled notebooks, environment settings, or mounts, run `down` followed by `up` to recreate the containers with the changes. Do not remove the data volume unless you intend to delete its stored objects.

If startup fails, inspect the logs above, fix the problem, and rerun `up`. A timeout on port 8888 or 8181 can indicate a container startup failure or a conflicting port. WSLC resources are separate from Docker Desktop's resources; use `wslc`, not `docker`, to inspect this deployment.

## Docker / Podman: Step 0 – Prerequisites

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
| Jupyter "Kernel Restarting" on `sc.to_arrow().to_pandas()` | Out of memory. Raise the Podman VM memory (see *Using Podman*) or add `limit=` / `selected_fields=` to `tbl.scan(...)`. |
| `%sql`: `Catalog Error: Table with name df does not exist!` | See *Querying PyIceberg data with DuckDB*: create a real DuckDB table and make sure the right connection is active. |
| `%sql`: `KeyError: 'DEFAULT'` | jupysql vs. prettytable ≥ 3.12. Rebuild/recreate the image to apply the bundled IPython configuration (`docker compose up -d --build`, or WSLC `down` then `up`), or run `%config SqlMagic.style = "_DEPRECATED_DEFAULT"` in the notebook. |
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
