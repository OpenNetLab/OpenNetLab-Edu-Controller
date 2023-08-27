#! /bin/bash

[[ $# -ne 1 ]] && exit

cmd=$1
apps=("account" "announcement" "conf" "contest" "options" "problem" "submission")

clean() {
  rm -rf ./data/zips
  rm -rf ./data/problems
  rm -rf ./data/submissions
  find . -type d -name 'migrations' -not -path './venv/*' | xargs rm -r;
  rm onl.db
  docker rm -f oj-redis-dev
}

if [[ $cmd == "make" || $cmd == "makemigrations" ]]; then
  for app in "${apps[@]}"; do
    python3 manage.py makemigrations $app
  done
elif [[ $cmd == "migrate" ]]; then
  python3 manage.py migrate
  python manage.py inituser --username=root --password=rootroot --action=create_super_admin
elif [[ $cmd == "clean" ]]; then
  clean
elif [[ $cmd == "rebuild" ]]; then
  clean
  for app in "${apps[@]}"; do
    python3 manage.py makemigrations $app
  done
  python3 manage.py migrate
  python manage.py inituser --username=root --password=rootroot --action=create_super_admin
elif [[ $cmd == "run" ]]; then
  # run dramatiq
  pgrep dramatiq > /dev/null
  
  if [[ $? -ne 0 ]]; then
    echo "running dramatiq ..."
    python3 manage.py rundramatiq &>data/log/dramatiq.log &
  else
    echo "dramatiq is already running ..."
  fi
  docker container ls > /dev/null
  
  if [[ $? -ne 0 ]]; then
    echo "running redis in docker ..."
    docker run -it -d -p 6380:6379 --name oj-redis-dev redis:4.0-alpine
  else
    echo "redis is already running"
  fi

  python3 manage.py runserver 0.0.0.0:7890
fi
