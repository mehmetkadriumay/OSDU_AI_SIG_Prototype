from pyspark.sql import SparkSession

spark = SparkSession.builder.appName("osdu-ddl").getOrCreate()

# adjust the path if the file is somewhere else in the container
ddl = open("/home/iceberg/notebooks/notebooks/osdu_well_prototype_iceberg.sql", encoding="utf-8").read()

statements = []
for chunk in ddl.split(";\n"):
    body = "\n".join(l for l in chunk.splitlines() if not l.strip().startswith("--")).strip()
    if body:
        statements.append(body)

for i, stmt in enumerate(statements, 1):
    try:
        spark.sql(stmt)
    except Exception as e:
        print(f"FAILED at statement {i}:\n{stmt[:200]}\n{e}")
        raise
    if i % 25 == 0:
        print(f"{i}/{len(statements)}")

print("done:", len(statements), "statements")
spark.sql("SHOW TABLES IN demo.master_data").show(50, truncate=False)
