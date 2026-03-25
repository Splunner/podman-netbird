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
[podmanadm@alma-4gb-nbg1-7 helper_scripts]$ cat pg_backup.sh 
#!/bin/bash

# ============================================================
# CONFIGURATION
# ============================================================

POSTGRES_CONTAINER="${1:-my_postgres}"
POSTGRES_USER="${2:-postgres}"
BACKUP_DEST="${3:-/backup}"
POSTGRES_DB="${4:-my_database}"

# FLAGS
DUMP_ALL=false
CLEAN=false

for arg in "$@"; do
    case $arg in
        --dump-all) DUMP_ALL=true ;;
        --clean)    CLEAN=true ;;
    esac
done

# ============================================================

TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)

if [ "$DUMP_ALL" = "true" ]; then
    FILENAME="postgres_${POSTGRES_CONTAINER}_ALL_${TIMESTAMP}.sql.gz"
else
    if [ -z "$POSTGRES_DB" ] || [ "$POSTGRES_DB" = "my_database" ]; then
        echo "[ERROR] Database name required when not using --dump-all"
        echo "Usage: $0 <container> <user> <backup_dest> <database> [--dump-all] [--clean]"
        exit 1
    fi
    FILENAME="postgres_${POSTGRES_CONTAINER}_${POSTGRES_DB}_${TIMESTAMP}.sql.gz"
fi

FULL_PATH="${BACKUP_DEST}/${FILENAME}"

mkdir -p "$BACKUP_DEST"

echo "=== PostgreSQL Dump ==="
echo "Container : $POSTGRES_CONTAINER"
echo "User      : $POSTGRES_USER"
echo "Database  : $([ "$DUMP_ALL" = "true" ] && echo "ALL (pg_dumpall)" || echo "$POSTGRES_DB")"
echo "Clean     : $CLEAN"
echo "File      : $FULL_PATH"
echo ""

EXTRA_FLAGS=""
if [ "$CLEAN" = "true" ]; then
    EXTRA_FLAGS="--clean --if-exists"
fi

if [ "$DUMP_ALL" = "true" ]; then
    echo "[INFO] Running pg_dumpall..."
    podman exec -t "$POSTGRES_CONTAINER" pg_dumpall -U "$POSTGRES_USER" $EXTRA_FLAGS \
        | gzip > "$FULL_PATH"
else
    echo "[INFO] Running pg_dump..."
    podman exec -t "$POSTGRES_CONTAINER" pg_dump -U "$POSTGRES_USER" $EXTRA_FLAGS "$POSTGRES_DB" \
        | gzip > "$FULL_PATH"
fi

if [ $? -eq 0 ]; then
    echo "[OK] Backup saved: $FULL_PATH"
    echo "Size: $(du -sh "$FULL_PATH" | cut -f1)"
else
    echo "[ERROR] Backup failed!"
    exit 1
fi