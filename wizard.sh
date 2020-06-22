#!/bin/bash

touch -a .env
docker-compose run --rm wizard "$@"
