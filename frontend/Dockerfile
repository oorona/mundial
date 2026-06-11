FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

# Build-time environment variables (NEXT_PUBLIC_* are baked into the client bundle)
ARG NEXT_PUBLIC_APP_NAME
ENV NEXT_PUBLIC_APP_NAME=$NEXT_PUBLIC_APP_NAME
# Discord Embedded App SDK client id — required by the Activity handshake
# (frontend/lib/activity.ts reads process.env.NEXT_PUBLIC_DISCORD_CLIENT_ID).
ARG NEXT_PUBLIC_DISCORD_CLIENT_ID
ENV NEXT_PUBLIC_DISCORD_CLIENT_ID=$NEXT_PUBLIC_DISCORD_CLIENT_ID

RUN npm run build

CMD ["npm", "start"]
