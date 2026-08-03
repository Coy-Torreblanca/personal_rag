# Installation and Deployment
## Installation

```bash
brew install podman
brew install podman-compose
```

## Configuration

Create a .env file in root dir.
Example - 
```
## 30AI
R2_ACCOUNT_ID=<some_value>
R2_S3_API=<some_value>
R2_TOKEN_VALUE=<some_value>
R2_ACCESS_ID=<some_value>
R2_SECRET_ACCESS_KEY=<some_value>
BUCKET_NAME=30aidev
MODAL_TOKEN_ID=<some_value>
MODAL_TOKEN_SECRET=<some_value>
OPENAI_API_KEY=<some_value>
COHERE_API_KEY=<some_value>
LOG_LEVEL=DEBUG
DEEPSEEK_API_KEY=<some_value>
NEXT_PUBLIC_API_URL=100.73.123.10
CORS_ALLOWED_ORIGINS=100.73.123.10
```
## Deployment

From root project dir, run the following to spin up the containers (or redploy).

```bash
podman-compose down
podman-compose --env-file .env up -d --build 
```

# Testing

Run the following to load env vars in this terminal.
```bash
export $(grep -v '^#' .env | xargs)
```

