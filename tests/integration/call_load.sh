#/bin/bash
set -u
index=$1

tmpf=$(mktemp)
index=${index} envsubst <tests/integration/loadtest2.yaml.template >${tmpf}

kubectl apply -f ${tmpf}
