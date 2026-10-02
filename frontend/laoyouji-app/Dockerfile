FROM node:20-slim

WORKDIR /app

# Cache package installation
COPY package*.json ./
RUN npm install

# Copy source code
COPY . .

EXPOSE 5174

ENV HOST=0.0.0.0
ENV PORT=5174

CMD ["npm", "run", "dev:h5"]
