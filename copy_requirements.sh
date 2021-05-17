#!/bin/bash
set -e

echo "Copying requirement files back to host ..."
IMAGE_NAME=aws-setup-wizard_dev
TEMP_CONTAINER_NAME="$IMAGE_NAME-temp"

docker create --name $TEMP_CONTAINER_NAME $IMAGE_NAME
docker cp $TEMP_CONTAINER_NAME:/usr/app/requirements.txt requirements.txt
docker cp $TEMP_CONTAINER_NAME:/usr/app/dev-requirements.txt dev-requirements.txt
docker rm $TEMP_CONTAINER_NAME

echo "Done copying requirement files back to host."
