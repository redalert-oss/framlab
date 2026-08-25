#!/bin/zsh
set -e
cd "${0:A:h}"
npm run setup
exec npm start
