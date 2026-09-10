FROM odoo:17.0

USER root
RUN apt-get update && apt-get install -y libatlas-base-dev
RUN pip3 install numpy numpy-financial
USER odoo