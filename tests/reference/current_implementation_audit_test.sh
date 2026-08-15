#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu

repo=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
audit="$repo/reference/audits/current-implementation.json"
summary="$repo/docs/audits/current-implementation.md"
tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/wtwm-current-audit.XXXXXX")
trap 'rm -rf "$tmpdir"' EXIT HUP INT TERM
validator="$tmpdir/validate.py"

cat > "$validator" <<'PY'
import json
import pathlib
import re
import sys
from collections import Counter

repo = pathlib.Path(sys.argv[1])
audit_path = pathlib.Path(sys.argv[2])
summary_path = pathlib.Path(sys.argv[3])
expected_categories = ["directive", "action", "construct", "runtime_dispatch"]
expected_statuses = ["effective", "not_applicable", "parsed_only", "unavailable", "unknown"]
required = ["id", "category", "name", "evidence", "tests", "native_wayland_status", "xwayland_status", "unknowns", "notes"]
nondeterministic = {"timestamp", "generated_at", "host", "hostname", "cwd", "absolute_path"}
location_re = re.compile(r"^([^/:][^:]*)\:([1-9][0-9]*)$")

def reject(message):
    raise ValueError(message)

def validate_location(location):
    match = location_re.fullmatch(location)
    if not match or pathlib.PurePosixPath(match.group(1)).is_absolute() or ".." in pathlib.PurePosixPath(match.group(1)).parts:
        reject(f"invalid repository-relative location: {location}")
    path = repo / match.group(1)
    if not path.is_file():
        reject(f"location path does not exist: {location}")
    if int(match.group(2)) > len(path.read_text().splitlines()):
        reject(f"location line is outside file: {location}")

def walk(value):
    if isinstance(value, dict):
        if nondeterministic.intersection(value):
            reject("nondeterministic field present")
        for child in value.values(): walk(child)
    elif isinstance(value, list):
        for child in value: walk(child)

raw = audit_path.read_text()
data = json.loads(raw)
walk(data)
if data.get("schema_version") != "1.0": reject("unexpected schema version")
if not re.fullmatch(r"[0-9a-f]{40}", data.get("audited_commit", "")): reject("invalid audited commit")
if data.get("status_enum") != expected_statuses: reject("status enum is not fixed and sorted")
schema = data.get("schema", {})
if schema.get("category_enum") != expected_categories: reject("category enum mismatch")
if schema.get("entry_required_fields") != required: reject("documented required fields mismatch")
entries = data.get("entries")
if not isinstance(entries, list) or not entries: reject("entries must be a non-empty array")
ids = []
for entry in entries:
    if list(entry) != required: reject(f"entry field order/fields mismatch: {entry.get('id')}")
    if entry["category"] not in expected_categories: reject("invalid category")
    if entry["native_wayland_status"] not in expected_statuses or entry["xwayland_status"] not in expected_statuses: reject("invalid status")
    if not re.fullmatch(r"(directive|action|construct|runtime_dispatch)\.[a-z0-9]+(?:-[a-z0-9]+)*", entry["id"]): reject("unstable ID syntax")
    ids.append(entry["id"])
    for field in ("evidence", "tests", "unknowns"):
        values = entry[field]
        if not isinstance(values, list) or values != sorted(set(values)): reject(f"{field} is not sorted/deduplicated")
    if not entry["evidence"]: reject("entry lacks evidence")
    for location in entry["evidence"] + entry["tests"]: validate_location(location)
    if not isinstance(entry["notes"], str) or not entry["notes"].strip(): reject("entry lacks notes")
if len(ids) != len(set(ids)): reject("duplicate stable ID")
normalize = lambda name: re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
ordered = sorted(entries, key=lambda e: (e["category"], normalize(e["name"]), e["id"]))
if entries != ordered: reject("entries are not deterministically ordered")
canonical = json.dumps(data, indent=2, ensure_ascii=True) + "\n"
if raw != canonical: reject("JSON formatting is not canonical")
summary = summary_path.read_text()
for heading, counts in (("category", Counter(e["category"] for e in entries)),
                        ("native_wayland_status", Counter(e["native_wayland_status"] for e in entries)),
                        ("xwayland_status", Counter(e["xwayland_status"] for e in entries))):
    for name, count in sorted(counts.items()):
        marker = f"| {heading} | `{name}` | {count} |"
        if marker not in summary: reject(f"summary count missing: {marker}")
if f"**Total entries:** {len(entries)}" not in summary: reject("summary total mismatch")
PY

python3 "$validator" "$repo" "$audit" "$summary"
cp "$audit" "$tmpdir/malformed.json"
python3 - "$tmpdir/malformed.json" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text())
data["entries"][0]["native_wayland_status"] = "invented-status"
data["entries"][1]["id"] = data["entries"][0]["id"]
path.write_text(json.dumps(data, indent=2) + "\n")
PY
if python3 "$validator" "$repo" "$tmpdir/malformed.json" "$summary" >/dev/null 2>&1; then
    echo "validator accepted deliberately malformed audit" >&2
    exit 1
fi
printf '%s\n' "current implementation audit validation passed (malformed input rejected)"
