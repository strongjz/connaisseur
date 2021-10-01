nr=$1

tmpf=$(mktemp)
filec=$(nr=${nr} envsubst <loadtest3.yaml >${tmpf})

kubectl apply -f ${tmpf}


