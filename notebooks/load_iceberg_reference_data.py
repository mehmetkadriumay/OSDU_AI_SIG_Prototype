"""Seed the prototype Iceberg reference tables from one enriched workbook.

Run load_iceberg_reference_data.ipynb in an Iceberg-enabled PySpark notebook.
Requires openpyxl and AllReferenceValues.iceberg.xlsx, not a repository checkout.
FIXED, OPEN and LOCAL are OSDU governance categories, not licensing grants.
Existing IDs are skipped, never overwritten; run only one loader at a time.
"""
import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path


_TOKEN = re.compile(r"\{\{[^{}]+\}\}")


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _replace(value, replacements):
    if isinstance(value, str):
        return _TOKEN.sub(lambda match: replacements.get(match[0], match[0]), value)
    if isinstance(value, list):
        return [_replace(item, replacements) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            new_key = _replace(key, replacements)
            if new_key in result:
                raise ValueError(f"Placeholder replacement produces duplicate key {new_key!r}")
            result[new_key] = _replace(item, replacements)
        return result
    return value


def _workbook_records(path):
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        if not {"Metadata", "Types", "ReferenceValues"}.issubset(workbook.sheetnames):
            raise ValueError("Use the enriched AllReferenceValues.iceberg.xlsx, not the four-column inventory")
        metadata = dict(workbook["Metadata"].iter_rows(min_row=2, values_only=True))
        if metadata.get("Format") != "OSDU-Iceberg-ReferenceValues/1":
            raise ValueError("Use the enriched AllReferenceValues.iceberg.xlsx workbook")
        specs = {}
        for entity, major, count in workbook["Types"].iter_rows(min_row=2, values_only=True):
            if (not isinstance(entity, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", entity)
                    or entity in specs or type(major) is not int or major < 1
                    or type(count) is not int or count < 1):
                raise ValueError(f"Invalid or duplicate workbook type: {entity!r}")
            specs[entity] = (major, count)
        if len(specs) != 47 or sum(count for _, count in specs.values()) != metadata.get("Records"):
            raise ValueError("Workbook Types must declare all 47 types and the correct total count")
        sheet = workbook["ReferenceValues"]
        rows = sheet.iter_rows(values_only=True)
        header = next(rows)
        if len(set(header)) != len(header):
            raise ValueError("Duplicate workbook columns")
        positions = {name: index for index, name in enumerate(header)}
        chunks = [name for name in header if isinstance(name, str) and name.startswith("Record_JSON_")]
        if (not {"Source_manifest", "Record_SHA256"}.issubset(positions) or not chunks
                or chunks != [f"Record_JSON_{i + 1}" for i in range(len(chunks))]):
            raise ValueError("Missing or unordered enriched-workbook JSON columns")
        grouped = {entity: {"records": {}, "sources": set(), "kinds": set()} for entity in specs}
        for number, row in enumerate(rows, 2):
            parts = [row[positions[name]] for name in chunks]
            if any(part is not None and not isinstance(part, str) for part in parts):
                raise ValueError(f"Non-text JSON payload in workbook row {number}")
            raw = "".join(part or "" for part in parts)
            if hashlib.sha256(raw.encode("utf-8")).hexdigest() != row[positions["Record_SHA256"]]:
                raise ValueError(f"Truncated or edited JSON payload in workbook row {number}")
            record = json.loads(raw)
            kind = record.get("kind", "")
            match = re.fullmatch(
                r"[\w.-]+:[\w.-]+:reference-data--([A-Za-z][A-Za-z0-9_]*):(\d+)\.\d+\.\d+", kind)
            if not match or match[1] not in specs or int(match[2]) != specs[match[1]][0]:
                raise ValueError(f"Unexpected record kind {kind!r} in workbook row {number}")
            record_id = record.get("id")
            if not isinstance(record_id, str) or not record_id:
                raise ValueError(f"Missing record id in workbook row {number}")
            group = grouped[match[1]]
            if record_id in group["records"]:
                raise ValueError(f"Duplicate record id in workbook: {record_id}")
            group["records"][record_id] = record
            group["kinds"].add(kind)
            group["sources"].add(row[positions["Source_manifest"]])
        for entity, group in grouped.items():
            if len(group["records"]) != specs[entity][1]:
                raise ValueError(f"Workbook record count mismatch for {entity}")
            group["records"] = list(group["records"].values())
            group["sources"] = sorted(group["sources"])
            group["kinds"] = sorted(group["kinds"])
        return grouped
    finally:
        workbook.close()


def _convert(value, schema, path=""):
    """Project to Spark's schema JSON without silently dropping populated values."""
    if value is None:
        return None
    typ = schema["type"] if isinstance(schema, dict) else schema
    if typ == "struct":
        if not isinstance(value, dict):
            raise ValueError(f"{path}: expected an object, found {type(value).__name__}")
        result = {}
        for field in schema["fields"]:
            name = field["name"]
            child_path = f"{path}.{name}" if path else name
            child = value.get(name)
            if child is None and not field["nullable"]:
                raise ValueError(f"{child_path}: missing non-null value")
            result[name] = _convert(child, field["type"], child_path)
        return result
    if typ == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path}: expected an array")
        if not schema["containsNull"] and any(item is None for item in value):
            raise ValueError(f"{path}: null array element")
        return [_convert(item, schema["elementType"], path + "[]") for item in value]
    if typ == "map":
        if not isinstance(value, dict):
            raise ValueError(f"{path}: expected a map")
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path}: non-string map key")
            if item is None and not schema["valueContainsNull"]:
                raise ValueError(f"{path}: null map value")
            # Apart from tags, string-valued maps represent arbitrary JSON objects
            # in the prototype DDL, with every value JSON-encoded.
            if schema["valueType"] == "string" and path != "tags":
                result[key] = _json(item)
            else:
                result[key] = _convert(item, schema["valueType"], path + "{}")
        return result
    if typ == "string":
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            return _json(value)
    elif typ == "boolean":
        if isinstance(value, bool):
            return value
    elif typ in ("long", "integer", "short", "byte"):
        if type(value) is int and -(2 ** 63) <= value < 2 ** 63:
            return value
    elif typ in ("double", "float"):
        if type(value) in (int, float) and math.isfinite(value):
            return float(value)
    elif typ in ("timestamp", "timestamp_ntz"):
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError(f"{path}: timestamp has no timezone")
            return parsed.astimezone(timezone.utc)
    elif typ == "date":
        if isinstance(value, str):
            return date.fromisoformat(value)
    raise ValueError(f"{path}: cannot convert {type(value).__name__} to {typ}")


def _prepare(records, schema, replacements):
    result = []
    ids = set()
    for record in records:
        resolved = _replace(record, replacements)
        raw = _json(resolved)
        if _TOKEN.search(raw):
            raise ValueError(f"Unresolved environment placeholder in {record['id']}")
        record_id = resolved["id"]
        if record_id in ids:
            raise ValueError(f"Duplicate record id after replacement: {record_id}")
        ids.add(record_id)
        row = _convert(resolved, schema)
        row["_raw_record"] = raw
        result.append(row)
    return result


def load_reference_data(
    spark,
    *,
    namespace,
    owners_group,
    viewers_group,
    legal_tag,
    country_code,
    workbook_path=None,
    catalog="osdu_iceberg",
    dry_run=True,
):
    """Preflight all 47 tables, then append only IDs absent from each target.

    dry_run=True performs table/schema checks and prepares every source record,
    but writes nothing. Source kinds, attribution and inactive values are retained.
    No schema/record versions are invented. _raw_record retains the substituted
    complete workbook record, including fields not represented by the target schema.
    The operation is restartable but is not atomic across all 47 tables.
    """
    replacements = {
        "{{NAMESPACE}}": namespace,
        "{{DATA_OWNERS_GROUP}}": owners_group,
        "{{DATA_VIEWERS_GROUP}}": viewers_group,
        "{{LEGAL_TAG}}": legal_tag,
        "{{ISO_3166_ALPHA_2_CODE}}": country_code,
    }
    if any(not isinstance(value, str) or not value.strip() or _TOKEN.search(value)
           for value in replacements.values()):
        raise ValueError("Set namespace, owners_group, viewers_group, legal_tag and country_code")
    if not re.fullmatch(r"[\w.-]+", namespace):
        raise ValueError("namespace must contain only word characters, dots or hyphens")
    if not re.fullmatch(r"[A-Z]{2}", country_code):
        raise ValueError("country_code must be an uppercase ISO 3166 alpha-2 code")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", catalog):
        raise ValueError("catalog must be a simple Spark catalog name")
    path = Path(workbook_path) if workbook_path else Path(__file__).with_name("AllReferenceValues.iceberg.xlsx")
    groups = _workbook_records(path)
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    prepared = []
    report = []
    for entity, group in groups.items():
        target = f"`{catalog}`.`reference_data`.`{entity}`"
        table = spark.table(target)
        schema = table.schema
        if "_raw_record" not in schema.fieldNames():
            raise ValueError(f"{target}: missing _raw_record; use the prototype Iceberg DDL")
        rows = _prepare(group["records"], schema.jsonValue(), replacements)
        # Verify the explicit schema on the driver before any table writes.
        frame = spark.createDataFrame(rows, schema=schema, verifySchema=True)
        prepared.append((target, frame, set(row["id"] for row in rows)))
        report.append({
            "table": entity,
            "source_records": len(rows),
            "source_workbook": str(path),
            "source_manifests": group["sources"],
            "source_kinds": group["kinds"],
            "inserted": 0,
            "already_present": 0,
            "status": "validated",
        })
        print(f"Validated {entity}: {len(rows):,} standard records")
    if dry_run:
        print(f"Dry run: {sum(item['source_records'] for item in report):,} records; no writes.")
        return report
    for (target, frame, source_ids), item in zip(prepared, report):
        existing = spark.table(target).select("id").distinct()
        missing = frame.join(existing, on="id", how="left_anti").select(*frame.columns)
        count = missing.count()
        if count:
            missing.writeTo(target).append()
        # Verify every requested ID is present after the append.
        remaining = frame.select("id").join(
            spark.table(target).select("id"), on="id", how="left_anti"
        ).limit(1).count()
        if remaining:
            raise RuntimeError(f"{target}: source IDs still missing after append")
        item.update(inserted=count, already_present=len(source_ids) - count, status="loaded")
        print(f"{item['table']}: inserted {count:,}; already present {item['already_present']:,}")
    return report
