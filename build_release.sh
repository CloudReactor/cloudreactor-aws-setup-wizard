#!/bin/bash
# This script builds the image for releasing into Docker Hub, and is not needed
# unless you're developing this project.

set -e

docker build -t aws-setup-wizard -t \
 cloudreactor/aws-setup-wizard .

docker login
docker tag aws-setup-wizard cloudreactor/aws-setup-wizard:latest
docker push cloudreactor/aws-setup-wizard:latest
docker tag aws-setup-wizard cloudreactor/aws-setup-wizard:1.4.0
docker push cloudreactor/aws-setup-wizard:1.4.0
docker tag aws-setup-wizard cloudreactor/aws-setup-wizard:1.4
docker push cloudreactor/aws-setup-wizard:1.4
docker tag aws-setup-wizard cloudreactor/aws-setup-wizard:1
docker push cloudreactor/aws-setup-wizard:1
