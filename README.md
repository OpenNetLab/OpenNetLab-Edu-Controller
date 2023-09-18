## installation & deploy

- __install OpenNetLab-Controller__

```
git clone <this-repo>; cd <this-repo>
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
```

- __install required programs__

```
sudo apt install redis supervisor nginx
```

## run


- __build onl-frontent__

for more details check [onl-fe](https://github.com/OpenNetLab/OpenNetLab-Edu-FE)


- __run onl-controller__

```
./manage migrate
FRONTEND="/frontend_path" ./manage run
```
- run nginx using local configuration

```
sudo nginx -c <absolute-dir-path>/nginx.conf
```

- make sure [onl-library](https://github.com/OpenNetLab/OpenNetLab-Edu) is installed
