FROM python:3.10
RUN pip install speedtest-cli PyMySQL loguru flask
COPY main.py /srv
RUN mkdir /srv/templates/
RUN mkdir /srv/graphs/
COPY templates/* /srv/templates/
WORKDIR /srv