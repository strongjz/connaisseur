#! /bin/bash
set -euo pipefail

# This script is expected to be called from the root folder of Connaisseur

echo 'Preparing Connaisseur config...'
yq eval-all --inplace 'select(fileIndex == 0) * select(fileIndex == 1)' helm/values.yaml tests/integration/load-update.yaml
echo 'Config set'

echo 'Installing Connaisseur...'
helm install connaisseur helm --atomic --create-namespace --namespace connaisseur || { echo 'Failed to install Connaisseur'; exit 1; }
echo 'Successfully installed Connaisseur'

echo 'Testing Connaisseur with complex requests...'
kubectl apply -f tests/integration/loadtest.yaml >output.log 2>&1 || true

if [[ ! ("$(cat output.log)" =~ 'deployment.apps/redis-with-many-instances created' && "$(cat output.log)" =~ 'pod/pod-with-many-containers created' && "$(cat output.log)" =~ 'pod/pod-with-many-containers-and-init-containers created' && "$(cat output.log)" =~ 'pod/pod-with-some-containers-and-init-containers created' && "$(cat output.log)" =~ 'pod/pod-with-coinciding-containers-and-init-containers created') ]]; then
  echo 'Failed test with complex requests. Output:'
  cat output.log
  kubectl logs -n connaisseur deployment/connaisseur-deployment > output.log
  cat output.log
  exit 1
else
  echo 'Successfully passed test with complex requests'
fi

echo 'Testing Connaisseur with many requests...'
# TODO

echo 'Uninstalling Connaisseur...'
helm uninstall connaisseur --namespace connaisseur || { echo 'Failed to uninstall Connaisseur'; exit 1; }
echo 'Successfully uninstalled Connaisseur'

rm output.log
echo 'Passed load test'
