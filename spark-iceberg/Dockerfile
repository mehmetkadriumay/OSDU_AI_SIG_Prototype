# tabulario/spark-iceberg with fixes for running the bundled notebooks on SeaweedFS.
FROM tabulario/spark-iceberg

# jupysql (%sql magic) breaks with prettytable >= 3.12: "KeyError: 'DEFAULT'"
RUN pip install --no-cache-dir "prettytable<3.12"

# The Java (IJava) kernel runs Spark in-process on Java 17, which needs these
# --add-opens flags ("cannot access class sun.nio.ch.DirectBuffer").
COPY patch_java_kernel.py /tmp/patch_java_kernel.py
RUN python3 /tmp/patch_java_kernel.py && rm /tmp/patch_java_kernel.py

# Notebooks fixed for this stack (SeaweedFS endpoint, namespace bugs, DuckDB %sql setup).
COPY notebooks/ /home/iceberg/notebooks/
