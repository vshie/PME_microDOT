FROM python:3.11-slim-bullseye

# Install minimal system dependencies
RUN apt-get update && apt-get install -y \
    psmisc \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Create logs directory inside the container
RUN mkdir -p /app/logs && chmod 777 /app/logs

# Copy app files (Flask backend and static Vue2 files)
COPY app/ .

# Install Python dependencies directly (without upgrading pip)
# Install each package separately to avoid hash verification issues
RUN pip install --no-cache-dir flask==2.0.1 && \
    pip install --no-cache-dir pyserial==3.5 && \
    pip install --no-cache-dir requests==2.28.1 && \
    pip install --no-cache-dir Werkzeug==2.0.3 && \
    pip install --no-cache-dir Jinja2==3.0.3 && \
    pip install --no-cache-dir MarkupSafe==2.0.1 && \
    pip install --no-cache-dir itsdangerous==2.0.1

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py

# Expose port for Flask
EXPOSE 6436

LABEL version="0.1"

ARG IMAGE_NAME
LABEL permissions='\
{\
  "ExposedPorts": {\
    "6436/tcp": {}\
  },\
  "HostConfig": {\
    "Binds": [\
      "/usr/blueos/extensions/dosensor:/app/logs",\
      "/dev/ttyUSB0:/dev/ttyUSB0",\
      "/dev/ttyUSB1:/dev/ttyUSB1",\
      "/dev/ttyUSB2:/dev/ttyUSB2",\
      "/dev/ttyUSB3:/dev/ttyUSB3",\
      "/dev/ttyACM0:/dev/ttyACM0",\
      "/dev/ttyACM1:/dev/ttyACM1"\
    ],\
    "ExtraHosts": ["host.docker.internal:host-gateway"],\
    "PortBindings": {\
      "6436/tcp": [\
        {\
          "HostPort": ""\
        }\
      ]\
    },\
    "NetworkMode": "host",\
    "Privileged": true\
  }\
}'

ARG AUTHOR
ARG AUTHOR_EMAIL
LABEL authors='[\
    {\
        "name": "Tony White",\
        "email": "tony@bluerobotics.com"\
    }\
]'

ARG MAINTAINER
ARG MAINTAINER_EMAIL
LABEL company='\
{\
        "about": "",\
        "name": "Tony White",\
        "email": "support@bluerobotics.com"\
    }'
LABEL type="tool"

ARG REPO
ARG OWNER
LABEL readme=''
LABEL links='\
{\
        "source": ""\
    }'
LABEL requirements="core >= 1.1"

ENTRYPOINT ["python", "-u", "/app/main.py"]
