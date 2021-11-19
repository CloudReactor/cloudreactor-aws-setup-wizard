#!/bin/bash

touch -a .env

# These variables are passed these from your environment to Docker Compose.
# Prevent warnings from Docker Compose if not defined.
if [ -z "$AWS_SESSION_TOKEN" ]; then export AWS_SESSION_TOKEN=''; fi
if [ -z "$AWS_DEFAULT_REGION" ]; then export AWS_DEFAULT_REGION=''; fi
if [ -z "$AWS_ACCESS_KEY_ID" ]; then export AWS_ACCESS_KEY_ID=''; fi
if [ -z "$AWS_SECRET_ACCESS_KEY" ]; then export AWS_SECRET_ACCESS_KEY=''; fi

docker compose run --rm wizard "$@"
