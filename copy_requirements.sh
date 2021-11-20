#!/bin/bash
set -e

echo "Copying requirement files back to host ..."
docker compose build pip-compile
docker compose run --rm pip-compile > requirements.txt
docker compose build pip-compile-dev
docker compose run --rm pip-compile-dev > dev-requirements.txt
echo "Done copying requirement files back to host."
