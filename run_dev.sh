#! /bin/bash

# psql_id=$(docker container ls | grep postgres | awk '{print $1}')
# if [[ $(echo $psql_id | wc -l) -ne 1 ]]; then
#         echo "postgres is not running!"
#         exit 1
# fi
# psql_ip=$(docker inspect $psql_id --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
redis_id=$(docker container ls | grep redis | awk '{print $1}')
if [[ $(echo $redis_id | wc -l) -ne 1 ]]; then
        echo "redis is not running!"
        exit 1
fi
redis_ip=$(docker inspect $redis_id --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
# echo $psql_ip
# echo $redis_ip
source venv/bin/activate
python3 manage.py rundramatiq &>logs/dramatiq.log  &
REDIS_IP=$redis_ip python3 manage.py runserver 127.0.0.1:8080
# POSTGRES_IP=$psql_ip REDIS_IP=$redis_ip python3 manage.py runserver 127.0.0.1:8080
