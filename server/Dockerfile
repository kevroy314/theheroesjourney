FROM node:22-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev --no-audit --no-fund
COPY index.js ./
ENV DATA_DIR=/data
EXPOSE 8071
CMD ["node", "index.js"]
