#!/bin/sh
set -eu

data_directory="$(dirname "${DATABASE_PATH:-/app/data/u_calc.db}")"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$data_directory"
    chown -R ucalc:ucalc "$data_directory"
    exec gosu ucalc "$@"
fi

if [ ! -d "$data_directory" ]; then
    mkdir -p "$data_directory"
fi
if [ ! -w "$data_directory" ]; then
    echo "Database directory is not writable: $data_directory" >&2
    exit 1
fi
exec "$@"
