# 「是啊吃什么」前端镜像（§12.4）：node 构建 -> nginx 托管 + 反代
# 构建期注入 VITE_API_BASE_URL / VITE_APP_NAME（§10 展示名，§16 决策 13）

FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci --registry=https://registry.npmmirror.com
COPY . .
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ARG VITE_APP_NAME=是啊吃什么
ENV VITE_APP_NAME=$VITE_APP_NAME
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
