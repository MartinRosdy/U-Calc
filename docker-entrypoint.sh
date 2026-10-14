#!/bin/sh
set -eu
umask 077

database_path="${DATABASE_PATH:-/app/data/u_calc.db}"
data_directory="$(
    python3 -c 'import sys; from pathlib import Path; print(Path(sys.argv[1]).expanduser().resolve(strict=False).parent)' "$database_path"
)"

case "$data_directory" in
    /app/data|/app/data/*) ;;
    *)
        echo "DATABASE_PATH must point to a file inside /app/data: $database_path" >&2
        exit 1
        ;;
esac

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$data_directory"
    chown -R ucalc:ucalc "$data_directory"
    exec setpriv --reuid=ucalc --regid=ucalc --init-groups --no-new-privs "$@"
fi

if [ ! -d "$data_directory" ]; then
    mkdir -p "$data_directory"
fi
if [ ! -w "$data_directory" ]; then
    echo "Database directory is not writable: $data_directory" >&2
    exit 1
fi
exec "$@"
