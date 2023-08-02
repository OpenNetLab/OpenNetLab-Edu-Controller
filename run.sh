#! /bin/bash

[[ $# -ne 1 ]] && exit

cmd=$1
apps=("account" "announcement" "conf" "contest" "options" "problem" "submission")

if [[ $cmd == "make" || $cmd == "makemigrations" ]]; then
  for app in "${apps[@]}"; do
    python3 manage.py makemigrations $app
  done
elif [[ $cmd == "migrate" ]]; then
  python3 manage.py migrate
  python manage.py inituser --username=root --password=rootroot --action=create_super_admin
elif [[ $cmd == "clean" ]]; then
  find . -type d -name 'migrations' -not -path './venv/*' | xargs rm -r;
  rm onl.db
fi
