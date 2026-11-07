# tabulario/spark-iceberg with fixes for the bundled Jupyter notebooks.
FROM tabulario/spark-iceberg

# jupysql (%sql magic) breaks with prettytable >= 3.12: "KeyError: 'DEFAULT'"
RUN pip install --no-cache-dir "prettytable<3.12"
