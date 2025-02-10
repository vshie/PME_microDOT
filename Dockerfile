FROM python:3.11-slim-bullseye

# Install system dependencies
RUN apt-get update && apt-get install -y \
    psmisc \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy app files (Flask backend and static Vue2 files)
COPY app/ .

# Install Python dependencies (Flask and pySerial)
RUN pip install flask pyserial
# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py

# Expose port 6423 for Flask
EXPOSE 6423

LABEL version="0.1"

ARG IMAGE_NAME
LABEL permissions='\
{\
  "ExposedPorts": {\
    "6423/tcp": {}\
  },\
  "HostConfig": {\
    "ExtraHosts": ["host.docker.internal:host-gateway"],\
    "PortBindings": {\
      "6423/tcp": [\
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
LABEL requirements="core >= 1.0"

# Optionally, mark /dev/ttyUSB0 as a volume to allow access to the serial device.
VOLUME ["/dev/ttyUSB0"]

ENTRYPOINT ["python", "-u", "/app/app.py"]
