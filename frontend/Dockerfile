# Dev-mode frontend container (Vite dev server with HMR).
# Production build (Phase 8) is a static `npm run build` deployed to the
# portfolio host - no container needed there.
FROM node:22-slim
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]
