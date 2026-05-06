# To build image

**From project root**

podman build -t apitest -f apps/api/Dockerfile .

# To run container:

podman run --rm -p 8000:8000 --env-file .env localhost/apitest

# To run the app

 podman-compose --env-file .env up -d --build api
