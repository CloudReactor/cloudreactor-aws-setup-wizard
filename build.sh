#!/bin/bash

# Run this the first time you clone this repository or whenever you pull the branch.

touch -a .env
docker-compose build wizard
echo ""
echo "The CloudReactor AWS Quick Start Wizard is now built and ready to run!"
echo "Run it by typing"
echo ""
echo "  ./wizard.sh"
echo ""