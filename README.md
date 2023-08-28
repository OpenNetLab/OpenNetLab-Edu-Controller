## installation & deploy

- __install OpenNetLab-Controller__

```
git clone <this-repo>; cd <this-repo>
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
```

- __install docker__

## run

- __first run onl-controller__

```
./manage migrate
./manage run
```

- __then run onl-frontent__

for more details check [https://github.com/OpenNetLab/OpenNetLab-Edu-Controller](onl-fe)

- run nginx using local configuration

```
sudo nginx -c <absolute-dir-path>/nginx.conf
```
