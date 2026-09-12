#!/bin/sh
set -eu
API="${API_INTERNAL_URL:-http://backend:8000}"
API="${API%/}"
export API
i=0
while [ "$i" -lt 40 ]; do
  if node -e "fetch(process.env.API + '/health').then((r)=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"; then
    exec node server.js
  fi
  i=$((i + 1))
  sleep 2
done
echo "Farm API at ${API} did not become ready; starting UI anyway"
exec node server.js
