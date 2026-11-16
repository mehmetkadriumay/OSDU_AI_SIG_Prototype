# tabulario/spark-iceberg with fixes for running the bundled notebooks on SeaweedFS.
FROM tabulario/spark-iceberg

# jupysql's DEFAULT style was renamed in prettytable >= 3.12.
RUN mkdir -p /root/.ipython/profile_default && \
    printf 'c.SqlMagic.style = "_DEPRECATED_DEFAULT"\n' >> /root/.ipython/profile_default/ipython_config.py

# The Java (IJava) kernel runs Spark in-process on Java 17, which needs these
# --add-opens flags ("cannot access class sun.nio.ch.DirectBuffer").
COPY patch_java_kernel.py /tmp/patch_java_kernel.py
RUN python3 /tmp/patch_java_kernel.py && rm /tmp/patch_java_kernel.py

# Notebooks fixed for this stack (SeaweedFS endpoint, namespace bugs, DuckDB %sql setup).
COPY notebooks/ /home/iceberg/notebooks/
