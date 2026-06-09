#!/bin/bash
rsync -av \
  --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
  --exclude '*.pyc' --exclude '*.egg-info' --exclude 'companion' \
  --exclude 'node_modules' --exclude 'site' --exclude 'docs' \
  --exclude 'hardware' --exclude 'tests' --exclude 'deploy' \
  --exclude 'requirements-docs.txt' \
  --exclude 'mkdocs.yml' \
  /Users/mohrt/PiWallet/ pisv@piwalletsv32.local:PiWallet/
