#!/bin/bash

# ============================================================
# CONFIGURATION
# ============================================================

BACKUP_FILE="${1}"

# ============================================================
# CHECKS
# ============================================================

if [ -z "$BACKUP_FILE" ]; then
    echo "Usage: $0 <backup_file.tar.gz>"
    echo "Example: $0 /opt/storage/backup_2024-01-15_14-30-00.tar.gz"
    exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "[ERROR] File not found: $BACKUP_FILE"
    exit 1
fi

# Check integrity
echo "=== Integrity Check ==="
gzip -t "$BACKUP_FILE"
if [ $? -eq 0 ]; then
    echo "[OK] Archive is valid"
else
    echo "[ERROR] Archive is corrupted!"
    exit 1
fi

# ============================================================
# INFO
# ============================================================

echo ""
echo "=== Archive Info ==="
echo "File     : $BACKUP_FILE"
echo "Size     : $(du -sh "$BACKUP_FILE" | cut -f1)"
echo "Created  : $(stat -c '%y' "$BACKUP_FILE" | cut -d'.' -f1)"
echo "Unpacked : $(gzip -l "$BACKUP_FILE" | awk 'NR==2 {print $2}' | numfmt --to=iec)"

# ============================================================
# CONTENTS
# ============================================================

echo ""
echo "=== Directory Tree ==="
tar -tzf "$BACKUP_FILE" | grep "/$" | sed 's|[^/]*/|  |g'

echo ""
echo "=== All Files ==="
tar -tzf "$BACKUP_FILE" | grep -v "/$"

echo ""
echo "=== SQL Dumps ==="
tar -tzf "$BACKUP_FILE" | grep "\.sql\.gz$"

echo ""
echo "=== File Count ==="
echo "Directories : $(tar -tzf "$BACKUP_FILE" | grep  "/$"  | wc -l)"
echo "Files       : $(tar -tzf "$BACKUP_FILE" | grep -v "/$" | wc -l)"
echo "SQL Dumps   : $(tar -tzf "$BACKUP_FILE" | grep "\.sql\.gz$" | wc -l)"